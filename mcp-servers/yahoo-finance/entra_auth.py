# ============================================================
# Entra ID JWT verifier for FastMCP servers.
#
# Replaces the static StaticTokenVerifier with proper Entra JWT validation.
# Implements the FastMCP TokenVerifier protocol (async verify_token method).
#
# Runtime behaviour:
#   Production (ENTRA_TENANT_ID set):
#     - Validates Bearer token as an Entra-issued JWT via JWKS
#     - Audience must match MCP_CLIENT_ID (this server's app registration)
#     - Returns decoded claims dict on success; None on failure
#
#   Dev mode (ENTRA_TENANT_ID not set):
#     - Falls back to static token comparison against MCP_AUTH_TOKEN env var
#     - No row-level security needed (Yahoo Finance serves public market data)
#
# Helper functions (used inside MCP tool functions):
#   get_claims_from_request() — returns decoded token claims
#   check_scope(scope)        — raises PermissionError if token lacks scope
#
# Reference:
#   https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens
# ============================================================

import base64
import json
import logging
import os
import time
from typing import Any

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "")
_STATIC_DEV_TOKEN: str = os.getenv("MCP_AUTH_TOKEN", "dev-yahoo-mcp-token")

# Comma-separated list of additional trusted OIDC issuers (e.g. Okta).
# Entra (ENTRA_TENANT_ID) is always trusted. Only set this to add more IdPs.
TRUSTED_ISSUERS_RAW: str = os.getenv("TRUSTED_ISSUERS", "")

_WELL_KNOWN_OPENID = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
)

_jwks_uri: str | None = None
_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_issuer_jwks_cache: dict[str, dict] = {}
_JWKS_TTL: float = float(os.getenv("JWKS_CACHE_TTL", "3600"))  # seconds


# ---------------------------------------------------------------------------
# JWKS helpers
# ---------------------------------------------------------------------------

async def _get_jwks() -> dict[str, Any]:
    global _jwks_uri, _jwks_cache, _jwks_fetched_at
    if _jwks_cache and (time.monotonic() - _jwks_fetched_at) < _JWKS_TTL:
        return _jwks_cache

    async with httpx.AsyncClient(timeout=10) as client:
        if not _jwks_uri:
            url = _WELL_KNOWN_OPENID.format(tenant_id=ENTRA_TENANT_ID)
            resp = await client.get(url)
            resp.raise_for_status()
            _jwks_uri = resp.json()["jwks_uri"]

        resp = await client.get(_jwks_uri)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_fetched_at = time.monotonic()

    return _jwks_cache  # type: ignore[return-value]


async def _get_jwks_for_issuer(issuer: str) -> dict[str, Any]:
    """Discover and cache JWKS for any OIDC-compliant issuer (multi-IDP support)."""
    cached = _issuer_jwks_cache.get(issuer, {})
    if cached.get("jwks") and (time.monotonic() - cached.get("fetched_at", 0.0)) < _JWKS_TTL:
        return cached["jwks"]

    async with httpx.AsyncClient(timeout=10) as client:
        oidc_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
        resp = await client.get(oidc_url)
        resp.raise_for_status()
        jwks_uri = resp.json()["jwks_uri"]

        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        jwks = resp.json()
        _issuer_jwks_cache[issuer] = {"jwks": jwks, "fetched_at": time.monotonic()}
    return jwks


def _decode_claims_unsafe(token: str) -> dict[str, Any]:
    """Base64-decode JWT claims without signature verification.

    Safe to call ONLY after the signature has been cryptographically verified
    by EntraTokenVerifier (i.e. inside an authenticated MCP tool function).
    """
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padding = 4 - len(parts[1]) % 4
    padded = parts[1] + "=" * padding
    try:
        return json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# FastMCP-compatible token verifier
# ---------------------------------------------------------------------------

class EntraTokenVerifier(TokenVerifier):
    """FastMCP TokenVerifier that validates Entra ID Bearer tokens via JWKS.

    Register as ``mcp = FastMCP(auth=EntraTokenVerifier())``.

    Production: validates the OBO token the backend sends.
    Dev mode: falls back to static token comparison.
    """

    def __init__(self) -> None:
        super().__init__()

    async def verify_token(self, token: str) -> AccessToken | None:
        if not ENTRA_TENANT_ID:
            if token == _STATIC_DEV_TOKEN:
                return AccessToken(
                    token=token,
                    client_id="backend-service",
                    scopes=[],
                    claims={"sub": "backend-service", "dev_mode": True},
                )
            return None

        try:
            from jose import JWTError, jwt

            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            jwks = await _get_jwks()
            rsa_key: dict[str, str] = {}
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
                    break

            if not rsa_key:
                global _jwks_cache
                _jwks_cache = None
                logger.warning("JWKS key id=%s not found; cache invalidated", kid)
                return None

            issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
            claims: dict[str, Any] = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=f"api://{MCP_CLIENT_ID}",
                issuer=issuer,
            )
            return AccessToken(
                token=token,
                client_id=claims.get("azp") or claims.get("appid") or claims.get("sub") or "",
                scopes=claims.get("scp", "").split() if claims.get("scp") else [],
                expires_at=claims.get("exp"),
                claims=claims,
            )

        except Exception as exc:
            logger.warning("Token verification failed: %s", exc)
            return None


class MultiIDPTokenVerifier(EntraTokenVerifier):
    """Extends EntraTokenVerifier to accept tokens from multiple OIDC identity providers.

    Activation: set TRUSTED_ISSUERS env var to a comma-separated list of additional
    OIDC-compliant issuer URLs.  Falls back to pure Entra validation when not set.

    Example::

        TRUSTED_ISSUERS=https://dev-xxxxx.okta.com,https://dev-yyyyy.okta.com/oauth2/default
    """

    def __init__(self) -> None:
        super().__init__()  # calls TokenVerifier.__init__() — required for get_middleware()
        self._extra_issuers: list[str] = [
            i.strip() for i in TRUSTED_ISSUERS_RAW.split(",") if i.strip()
        ] if TRUSTED_ISSUERS_RAW else []

    async def verify_token(self, token: str) -> AccessToken | None:
        if not self._extra_issuers:
            return await super().verify_token(token)

        if not ENTRA_TENANT_ID:
            return await super().verify_token(token)

        try:
            from jose import jwt

            unverified_claims = jwt.get_unverified_claims(token)
            iss: str = unverified_claims.get("iss", "")

            entra_issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
            all_trusted = [entra_issuer] + self._extra_issuers

            if iss not in all_trusted:
                logger.warning("Rejected token: issuer %r not in trusted list", iss)
                return None

            if iss == entra_issuer:
                return await super().verify_token(token)

            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            jwks = await _get_jwks_for_issuer(iss)
            rsa_key: dict[str, str] = {}
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
                    break

            if not rsa_key:
                _issuer_jwks_cache.pop(iss, None)
                logger.warning("JWKS kid=%s not found for issuer %s; cache busted", kid, iss)
                return None

            claims: dict[str, Any] = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=f"api://{MCP_CLIENT_ID}",
                issuer=iss,
            )
            return AccessToken(
                token=token,
                client_id=claims.get("azp") or claims.get("appid") or claims.get("sub") or "",
                scopes=claims.get("scp", "").split() if claims.get("scp") else [],
                expires_at=claims.get("exp"),
                claims=claims,
            )

        except Exception as exc:
            logger.warning("Multi-IDP token verification failed: %s", exc)
            return None


# ---------------------------------------------------------------------------
# Helpers for use inside MCP tool functions
# ---------------------------------------------------------------------------

def get_claims_from_request() -> dict[str, Any]:
    """Decode and return claims from the current request's Bearer token.

    Signature has already been verified by EntraTokenVerifier; decoding
    without re-verification is safe inside authenticated tool functions.
    """
    try:
        from fastmcp.server.context import get_http_request  # type: ignore[import]
        req = get_http_request()
        if req:
            auth = req.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                return _decode_claims_unsafe(auth[7:])
    except Exception:
        pass
    return {}


def check_scope(required_scope: str) -> None:
    """Raise PermissionError if the current request token is missing ``required_scope``.

    In dev mode scope enforcement is skipped.

    Example::

        check_scope("market.read")
    """
    if not ENTRA_TENANT_ID:
        return  # dev mode: enforce nothing

    claims = get_claims_from_request()
    scopes = claims.get("scp", "").split()
    if required_scope not in scopes:
        logger.warning(
            "Scope check failed: required=%s present=%s",
            required_scope,
            scopes,
        )
        raise PermissionError(f"Missing required delegated scope: {required_scope}")


def get_caller_id() -> str:
    """Return the caller's stable identifier for audit logging.

    Returns the first non-empty value from: ``oid``, ``sub``, ``azp``
    (client/app ID), falling back to ``"anonymous"`` in dev mode.
    """
    claims = get_claims_from_request()
    return (
        claims.get("oid")
        or claims.get("sub")
        or claims.get("azp")
        or "anonymous"
    )


# ---------------------------------------------------------------------------
# Audit logging (MCP08 — per-tool structured audit trail)
# ---------------------------------------------------------------------------

def audit_log(
    tool: str,
    caller_id: str,
    outcome: str,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Emit a structured JSON audit entry for an MCP tool invocation.

    Fields
    ------
    event       — always ``"mcp_tool_call"``
    tool        — MCP tool name (e.g. ``"get_quote"``)
    caller_id   — caller identity from token claims (``oid`` / ``sub`` / ``azp``)
    outcome     — ``"success"`` | ``"error"`` | ``"denied"``
    duration_ms — wall-clock milliseconds for the tool body (optional)
    error       — exception message when outcome is not ``"success"`` (optional)

    Example log line (JSON)::

        {"event": "mcp_tool_call", "tool": "get_quote",
         "caller_id": "a1b2c3d4-...", "outcome": "success", "duration_ms": 45.2}
    """
    entry: dict[str, Any] = {
        "event": "mcp_tool_call",
        "tool": tool,
        "caller_id": caller_id,
        "outcome": outcome,
    }
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 1)
    if error:
        entry["error"] = error
    logger.info(json.dumps(entry))


# ---------------------------------------------------------------------------
# Content Safety (MCP06 — prompt-injection defense for tool arguments)
# ---------------------------------------------------------------------------

_cs_client: Any | None = None  # lazily initialised; None until first call


def _get_content_safety_client() -> Any | None:
    """Return a cached ``ContentSafetyClient`` if the endpoint env var is set."""
    global _cs_client
    if _cs_client is not None:
        return _cs_client
    endpoint = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
    if not endpoint:
        return None
    try:
        from azure.ai.contentsafety import ContentSafetyClient  # type: ignore[import]
        from azure.identity import DefaultAzureCredential
        _cs_client = ContentSafetyClient(
            endpoint=endpoint, credential=DefaultAzureCredential()
        )
        logger.info("Azure Content Safety client initialised (endpoint=%s)", endpoint)
    except Exception as exc:
        logger.warning("Content Safety client init failed: %s", exc)
    return _cs_client


def check_content_safety(text: str) -> None:
    """Scan *text* for harmful or injected content via Azure AI Content Safety.

    Raises ``ValueError`` if any category exceeds severity 4 (medium).
    No-op when ``AZURE_CONTENT_SAFETY_ENDPOINT`` is not configured (dev mode or
    feature disabled).  API errors are logged but do **not** block the request.

    Call before regex / whitelist validation for defense-in-depth::

        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
    """
    client = _get_content_safety_client()
    if client is None:
        return
    try:
        from azure.ai.contentsafety.models import AnalyzeTextOptions  # type: ignore[import]
        response = client.analyze_text(AnalyzeTextOptions(text=text))
        for item in response.categories_analysis:
            if item.severity and item.severity >= 4:
                logger.warning(
                    "Content Safety flagged input (category=%s severity=%d)",
                    item.category,
                    item.severity,
                )
                raise ValueError(
                    f"Input rejected by content safety policy (category: {item.category})"
                )
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Content Safety check error (non-blocking): %s", exc)
