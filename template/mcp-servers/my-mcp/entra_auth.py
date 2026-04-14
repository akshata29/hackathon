# ============================================================
# Entra ID JWT verifier for FastMCP servers -- TEMPLATE VERSION
#
# Drop this file into your mcp-servers/<my-server>/ directory and import
# the helpers you need in server.py.
#
# Activation:
#   Set ENTRA_TENANT_ID + MCP_CLIENT_ID environment variables to enable
#   full JWT validation.  When these are unset the server falls back to
#   static token comparison (MCP_AUTH_TOKEN), which is safe for local dev.
#
# Multi-IDP support (option B):
#   Set TRUSTED_ISSUERS to a comma-separated list of additional OIDC
#   issuer URLs (e.g. Okta, custom IdP).  Entra is always trusted.
#   Example: TRUSTED_ISSUERS=https://dev-xxxxx.okta.com
#
# Reference implementation (production-grade with audit logging, Content
# Safety scanning, and full multi-IDP support):
#   mcp-servers/portfolio-db/entra_auth.py
#   mcp-servers/yahoo-finance/entra_auth.py
#
# Key exports:
#   EntraTokenVerifier     -- FastMCP auth provider (single Entra tenant)
#   MultiIDPTokenVerifier  -- FastMCP auth provider (Entra + extra OIDC IdPs)
#   get_user_id_from_request()  -- RLS: returns oid/sub/X-User-Id for the caller
#   check_scope(scope)          -- raises PermissionError if scope is missing
#   audit_log(tool, user_id, outcome)  -- structured audit trail
# ============================================================

import base64
import contextvars
import json
import logging
import os
import time
from typing import Any

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "")
_STATIC_DEV_TOKEN: str = os.getenv("MCP_AUTH_TOKEN", "dev-mcp-token-change-me")

# Comma-separated list of additional trusted OIDC issuers (multi-IDP / Option B).
# Entra is always trusted.  Leave empty for Entra-only mode.
TRUSTED_ISSUERS_RAW: str = os.getenv("TRUSTED_ISSUERS", "")

_WELL_KNOWN_OPENID = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
)

# Stores verified claims for the duration of a single request.
# Set by the verifier after successful validation; read by helpers inside tools.
_request_claims: contextvars.ContextVar[dict] = contextvars.ContextVar("_request_claims", default={})

# ---------------------------------------------------------------------------
# JWKS cache
# ---------------------------------------------------------------------------
_jwks_uri: str | None = None
_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_issuer_jwks_cache: dict[str, dict] = {}
_JWKS_TTL: float = float(os.getenv("JWKS_CACHE_TTL", "3600"))


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
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padding = 4 - len(parts[1]) % 4
    try:
        return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# FastMCP-compatible token verifier: single Entra tenant
# ---------------------------------------------------------------------------

class EntraTokenVerifier(TokenVerifier):
    """FastMCP TokenVerifier that validates Entra ID Bearer tokens via JWKS.

    Register with: mcp = FastMCP(auth=EntraTokenVerifier())

    Production (ENTRA_TENANT_ID set):
        Validates the OBO token the backend sends, confirming user identity
        and delegated scopes.
    Dev mode (ENTRA_TENANT_ID unset):
        Falls back to static token comparison against MCP_AUTH_TOKEN.
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        if not ENTRA_TENANT_ID:
            # Dev mode -- static token
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
            _request_claims.set(claims)
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


# ---------------------------------------------------------------------------
# FastMCP-compatible token verifier: Entra + additional OIDC IdPs (Option B)
# ---------------------------------------------------------------------------

class MultiIDPTokenVerifier(EntraTokenVerifier):
    """Extends EntraTokenVerifier to accept tokens from multiple OIDC identity providers.

    Activation: set TRUSTED_ISSUERS env var to a comma-separated list of additional
    OIDC-compliant issuer URLs.  Falls back to pure Entra validation when not set.

    Example::
        TRUSTED_ISSUERS=https://dev-xxxxx.okta.com,https://dev-yyyyy.okta.com/oauth2/default

    Token validation:
    - The token's 'iss' claim MUST appear in the trusted-issuers whitelist.
    - JWKS is auto-discovered from {iss}/.well-known/openid-configuration.
    - Audience must be api://{MCP_CLIENT_ID} for all IdPs.
    - JWKS is cached per issuer with a configurable TTL (JWKS_CACHE_TTL, default 1h).
    """

    def __init__(self) -> None:
        super().__init__()
        self._extra_issuers: list[str] = (
            [i.strip() for i in TRUSTED_ISSUERS_RAW.split(",") if i.strip()]
            if TRUSTED_ISSUERS_RAW else []
        )

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
            entra_v1_issuer = f"https://sts.windows.net/{ENTRA_TENANT_ID}/"
            all_trusted = [entra_issuer, entra_v1_issuer] + self._extra_issuers

            if iss not in all_trusted:
                logger.warning("Rejected token: issuer %r not in trusted list", iss)
                return None

            if iss in (entra_issuer, entra_v1_issuer):
                return await super().verify_token(token)

            # Non-Entra issuer: auto-discover JWKS and verify
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
                token, rsa_key, algorithms=["RS256"],
                audience=f"api://{MCP_CLIENT_ID}", issuer=iss,
            )
            _request_claims.set(claims)
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
    """Return claims from the current request's verified Bearer token."""
    claims = _request_claims.get()
    if claims:
        return claims
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


def get_user_id_from_request() -> str:
    """Return the authenticated user's stable identifier for row-level security.

    Production (ENTRA_TENANT_ID set):
        Returns 'oid' (Entra object ID) or 'sub' (OIDC standard for other IdPs)
        from the OBO token.

    Dev mode:
        Falls back to the X-User-Id header for backward compatibility.
    """
    if not ENTRA_TENANT_ID:
        try:
            from fastmcp.server.context import get_http_request  # type: ignore[import]
            req = get_http_request()
            if req:
                uid = req.headers.get("x-user-id", "").strip()
                return uid or "dev"
        except Exception:
            pass
        return "dev"

    claims = get_claims_from_request()
    return (
        claims.get("oid")
        or claims.get("sub")
        or claims.get("preferred_username")
        or "anonymous"
    )


def check_scope(required_scope: str) -> None:
    """Raise PermissionError if the current request token is missing required_scope.

    In dev mode (ENTRA_TENANT_ID unset) scope enforcement is skipped.

    Usage::
        check_scope("my-resource.read")
        user_id = get_user_id_from_request()
    """
    if not ENTRA_TENANT_ID:
        return  # dev mode: skip

    claims = get_claims_from_request()
    scopes = claims.get("scp", "").split()
    roles: list = claims.get("roles", [])
    if required_scope not in scopes and required_scope not in roles and "mcp.call" not in roles:
        logger.warning(
            "Scope check failed: required=%s scp=%s roles=%s oid=%s",
            required_scope, scopes, roles, claims.get("oid", "unknown"),
        )
        raise PermissionError(f"Missing required scope: {required_scope}")


def audit_log(
    tool: str,
    user_id: str,
    outcome: str,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Emit a structured JSON audit entry for an MCP tool invocation.

    Fields: event, tool, user_id, outcome, duration_ms (optional), error (optional).

    Usage::
        import time
        start = time.monotonic()
        try:
            result = do_work()
            audit_log("my_tool", user_id, "success", (time.monotonic()-start)*1000)
            return result
        except Exception as exc:
            audit_log("my_tool", user_id, "error", error=str(exc))
            raise
    """
    entry: dict[str, Any] = {"event": "mcp_tool_call", "tool": tool, "user_id": user_id, "outcome": outcome}
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 1)
    if error:
        entry["error"] = error
    logger.info("mcp_tool_call", extra={"custom_dimensions": entry})
