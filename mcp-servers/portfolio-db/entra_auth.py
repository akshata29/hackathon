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
#     - X-User-Id header is used for row-level security (unchanged behaviour)
#
# Helper functions (used inside MCP tool functions):
#   get_user_id_from_request()  — extracts oid / preferred_username for RLS
#   check_scope(scope)          — raises PermissionError if token lacks scope
#
# Reference:
#   https://learn.microsoft.com/en-us/entra/identity-platform/access-tokens
# ============================================================

import base64
import contextvars
import json
import logging
import math
import os
import re
import time
import uuid
from typing import Any

# Stores verified token claims for the duration of a single request.
# Set by EntraTokenVerifier / MultiIDPTokenVerifier after successful validation;
# read by check_scope() and get_claims_from_request() inside tool functions.
_request_claims: contextvars.ContextVar[dict] = contextvars.ContextVar("_request_claims", default={})

import httpx
from fastmcp.server.auth import AccessToken, TokenVerifier
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structured Security Event Logging — Camp 4: Monitoring & Telemetry (MCP-08)
# ---------------------------------------------------------------------------
# Event type constants align with camp4-monitoring/security-function-v2/shared/security_logger.py.
# Using extra={"custom_dimensions": ...} ensures Azure Monitor OpenTelemetry stores
# each field as a queryable dimension in Application Insights, enabling KQL:
#   traces | where customDimensions.event_type == "INJECTION_BLOCKED"
#           | summarize count() by bin(timestamp, 5m)

class SecurityEventType:
    """Structured security event type constants for KQL-queryable telemetry."""
    INJECTION_BLOCKED = "INJECTION_BLOCKED"
    PII_REDACTED = "PII_REDACTED"
    CREDENTIAL_DETECTED = "CREDENTIAL_DETECTED"
    INPUT_CHECK_PASSED = "INPUT_CHECK_PASSED"
    SECURITY_ERROR = "SECURITY_ERROR"


def log_security_event(
    event_type: str,
    category: str,
    message: str,
    severity: str = "INFO",
    extra_dimensions: dict[str, Any] | None = None,
) -> None:
    """Log a structured security event with custom dimensions.

    Uses ``extra={"custom_dimensions": ...}`` so Azure Monitor OpenTelemetry
    stores each key as a queryable dimension in Application Insights.  Falls
    back gracefully to plain structured logging when Azure Monitor is absent.
    """
    custom_dimensions: dict[str, Any] = {
        "event_type": event_type,
        "category": category,
        "correlation_id": str(uuid.uuid4()),
        "severity": severity,
    }
    if extra_dimensions:
        custom_dimensions.update(extra_dimensions)
    log_level = getattr(logging, severity.upper(), logging.INFO)
    logger.log(log_level, message, extra={"custom_dimensions": custom_dimensions})


# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "")
_STATIC_DEV_TOKEN: str = os.getenv("MCP_AUTH_TOKEN", "dev-portfolio-mcp-token")

# Comma-separated list of additional trusted OIDC issuers (e.g. Okta).
# Entra (ENTRA_TENANT_ID) is always trusted. Only set this to add more IdPs.
# Example: TRUSTED_ISSUERS=https://dev-xxxxx.okta.com,https://dev-yyyyy.okta.com/oauth2/default
TRUSTED_ISSUERS_RAW: str = os.getenv("TRUSTED_ISSUERS", "")
# Public HTTPS URL of this server (used in PRM responses and WWW-Authenticate headers).
# If unset, the URL is inferred from the incoming request (works for local dev).
RESOURCE_URL: str = os.getenv("RESOURCE_URL", "")
# Expected OID of the backend agent identity service principal.
# Leave empty to accept any valid app-only Entra token (less restrictive — dev/testing only).
AGENT_IDENTITY_ID: str = os.getenv("AGENT_IDENTITY_ID", "")

_WELL_KNOWN_OPENID = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
)

# ---------------------------------------------------------------------------
# JWKS cache — module-level with TTL (prevents using stale keys after rotation)
# ---------------------------------------------------------------------------
_jwks_uri: str | None = None
_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
# Per-issuer cache for multi-IDP mode: { issuer -> {"jwks": ..., "fetched_at": float} }
_issuer_jwks_cache: dict[str, dict] = {}
_JWKS_TTL: float = float(os.getenv("JWKS_CACHE_TTL", "3600"))  # seconds


# ---------------------------------------------------------------------------
# JWKS helpers
# ---------------------------------------------------------------------------

async def _get_jwks() -> dict[str, Any]:
    global _jwks_uri, _jwks_cache, _jwks_fetched_at
    # Serve from cache if still within TTL
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
    by the EntraTokenVerifier (i.e. inside an authenticated MCP tool function).
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

    In production: validates the OBO token the backend sends, confirming both
    the user's identity and the delegated scopes.
    In dev mode: falls back to static token comparison (no JWKS).
    """

    def __init__(self) -> None:
        super().__init__()

    async def verify_token(self, token: str) -> AccessToken | None:
        if not ENTRA_TENANT_ID:
            # Dev mode — compare against static token
            if token == _STATIC_DEV_TOKEN:
                return AccessToken(
                    token=token,
                    client_id="backend-service",
                    scopes=[],
                    claims={"sub": "backend-service", "dev_mode": True},
                )
            return None

        # Production — validate as Entra JWT
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
                # Key not found — may be a rotation event; flush cache and fail this request
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


class MultiIDPTokenVerifier(EntraTokenVerifier):
    """Extends EntraTokenVerifier to accept tokens from multiple OIDC identity providers.

    Activation: set TRUSTED_ISSUERS env var to a comma-separated list of additional
    OIDC-compliant issuer URLs (e.g. Okta).  Falls back to pure Entra validation
    when TRUSTED_ISSUERS is not set (fully backward-compatible).

    Example::

        TRUSTED_ISSUERS=https://dev-xxxxx.okta.com,https://dev-yyyyy.okta.com/oauth2/default

    Token validation rules:
    - The token's ``iss`` claim MUST appear in the trusted-issuers whitelist.
    - JWKS is auto-discovered from ``{iss}/.well-known/openid-configuration``.
    - Audience must be ``api://{MCP_CLIENT_ID}`` (same convention for all IdPs).
    - JWKS is cached per issuer with a configurable TTL (default 1 hour).

    Supported IdPs (tested):
    - Microsoft Entra ID (default, uses existing EntraTokenVerifier path)
    - Okta (Authorization Server issuer URL)
    - Any OIDC-compliant IdP that publishes a ``/.well-known/openid-configuration``
    """

    def __init__(self) -> None:
        super().__init__()  # calls TokenVerifier.__init__() — required for get_middleware()
        self._extra_issuers: list[str] = [
            i.strip() for i in TRUSTED_ISSUERS_RAW.split(",") if i.strip()
        ] if TRUSTED_ISSUERS_RAW else []

    async def verify_token(self, token: str) -> AccessToken | None:
        # No extra issuers configured → pure Entra path (no regression)
        if not self._extra_issuers:
            return await super().verify_token(token)

        # Dev mode (no ENTRA_TENANT_ID) → static token comparison
        if not ENTRA_TENANT_ID:
            return await super().verify_token(token)

        try:
            from jose import jwt

            # Read 'iss' from unverified claims to route to the right JWKS
            unverified_claims = jwt.get_unverified_claims(token)
            iss: str = unverified_claims.get("iss", "")

            entra_issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
            # client_credentials tokens are issued by the v1 STS endpoint
            entra_v1_issuer = f"https://sts.windows.net/{ENTRA_TENANT_ID}/"
            all_trusted = [entra_issuer, entra_v1_issuer] + self._extra_issuers

            if iss not in all_trusted:
                logger.warning("Rejected token: issuer %r not in trusted list", iss)
                return None

            if iss in (entra_issuer, entra_v1_issuer):
                # Both v1 and v2 Entra tokens use the same JWKS; validate with correct issuer
                if iss == entra_issuer:
                    return await super().verify_token(token)
                # v1 token: use Entra JWKS but validate with v1 issuer
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
                    logger.warning("JWKS kid=%s not found (v1 token); cache invalidated", kid)
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

            # Non-Entra issuer → auto-discover JWKS and verify
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            jwks = await _get_jwks_for_issuer(iss)
            rsa_key: dict[str, str] = {}
            for key in jwks.get("keys", []):
                if key.get("kid") == kid:
                    rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
                    break

            if not rsa_key:
                # Possible key rotation — bust issuer cache and reject this request
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


class AgentIdentityTokenVerifier(MultiIDPTokenVerifier):
    """Validates tokens issued to the backend's agent identity (no user OBO).

    The backend acquires an app-only token via DefaultAzureCredential (Managed
    Identity / agent blueprint credential — no stored client secret).  Unlike
    delegated OBO tokens, these carry no ``scp`` claim; they carry ``roles``
    and an ``oid`` that identifies the service principal.

    This class inherits all existing validation from MultiIDPTokenVerifier
    (signature, audience, issuer, multi-IDP support) and adds one extra check:
    when ``AGENT_IDENTITY_ID`` is set, app-only tokens (no ``scp``) must have a
    matching ``oid``.  Delegated user tokens (with ``scp``) are still accepted
    unchanged so that ``entra`` / ``multi-idp`` modes are not affected.

    Activation:
        Set ``AGENT_IDENTITY_ID`` to the agentIdentityId (OID of the Entra
        service principal) shown in the Azure portal under the Foundry project.
        Leave it empty to accept any app-only Entra token (dev/testing only).
    """

    async def verify_token(self, token: str) -> AccessToken | None:
        result = await super().verify_token(token)
        if result is None:
            return None
        # Only apply the oid guard for app-only tokens (no delegated scp claim).
        if AGENT_IDENTITY_ID and not (result.claims or {}).get("scp"):
            oid = (result.claims or {}).get("oid", "")
            if oid != AGENT_IDENTITY_ID:
                logger.warning(
                    "AgentIdentityTokenVerifier: rejected app-only token oid=%r (expected %r)",
                    oid,
                    AGENT_IDENTITY_ID,
                )
                return None
        return result


# ---------------------------------------------------------------------------
# Helpers for use inside MCP tool functions
# ---------------------------------------------------------------------------

def get_claims_from_request() -> dict[str, Any]:
    """Return claims from the current request's verified Bearer token.

    Prefers the ContextVar set by the verifier (most reliable); falls back
    to decoding the raw Authorization header when the ContextVar is unset.
    """
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
        Returns ``oid`` (Entra object ID — stable across UPN changes) from the
        OBO token.  This is the authoritative user key for RLS.

    Dev mode:
        Falls back to the ``X-User-Id`` header for backward compatibility with
        the static-token dev setup (no Entra configuration required locally).
    """
    if not ENTRA_TENANT_ID:
        # Dev mode — X-User-Id header (set by backend)
        try:
            from fastmcp.server.context import get_http_request  # type: ignore[import]
            req = get_http_request()
            if req:
                uid = req.headers.get("x-user-id", "").strip()
                return uid or "dev"
        except Exception:
            pass
        return "dev"

    # Production — oid from OBO token (cryptographically bound to the user).
    # For non-Entra IdPs (e.g. Okta), fall back to OIDC-standard 'sub' claim.
    claims = get_claims_from_request()
    return (
        claims.get("oid")                # Entra: stable object ID
        or claims.get("sub")             # OIDC standard (Okta, custom IdPs)
        or claims.get("preferred_username")
        or "anonymous"
    )


def check_scope(required_scope: str) -> None:
    """Raise PermissionError if the current request token is missing ``required_scope``.

    In dev mode (ENTRA_TENANT_ID not set) scope enforcement is skipped so that
    local development works without a full Entra setup.

    Call this at the start of any MCP tool that requires a specific delegated
    permission, e.g.::

        check_scope("portfolio.read")
        user_id = get_user_id_from_request()
    """
    if not ENTRA_TENANT_ID:
        return  # dev mode: enforce nothing

    claims = get_claims_from_request()
    # Delegated token (OBO / user flows): scopes in 'scp' as space-separated string
    # App token (client_credentials flow): permissions in 'roles' as a list
    # 'mcp.call' app role grants access to all tools (used by the okta-proxy).
    scopes = claims.get("scp", "").split()
    roles: list = claims.get("roles", [])
    # Agent-identity tokens (app-only, no scp): already oid-pinned by
    # AgentIdentityTokenVerifier — grant access without scope check.
    if not scopes and AGENT_IDENTITY_ID and claims.get("oid") == AGENT_IDENTITY_ID:
        return
    if required_scope not in scopes and required_scope not in roles and "mcp.call" not in roles:
        logger.warning(
            "Scope check failed: required=%s scp=%s roles=%s oid=%s",
            required_scope,
            scopes,
            roles,
            claims.get("oid", "unknown"),
        )
        raise PermissionError(f"Missing required scope: {required_scope}")


# ---------------------------------------------------------------------------
# Audit logging (MCP08 — per-tool structured audit trail)
# ---------------------------------------------------------------------------

def audit_log(
    tool: str,
    user_id: str,
    outcome: str,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Emit a structured JSON audit entry for an MCP tool invocation.

    Fields
    ------
    event       — always ``"mcp_tool_call"``
    tool        — MCP tool name (e.g. ``"get_holdings"``)
    user_id     — caller identity (``oid`` / ``sub`` / ``dev@localhost``)
    outcome     — ``"success"`` | ``"error"`` | ``"denied"``
    duration_ms — wall-clock milliseconds for the tool body (optional)
    error       — exception message when outcome is not ``"success"`` (optional)

    Example log line (JSON)::

        {"event": "mcp_tool_call", "tool": "get_holdings",
         "user_id": "alice@contoso.com", "outcome": "success", "duration_ms": 12.3}
    """
    entry: dict[str, Any] = {
        "event": "mcp_tool_call",
        "tool": tool,
        "user_id": user_id,
        "outcome": outcome,
    }
    if duration_ms is not None:
        entry["duration_ms"] = round(duration_ms, 1)
    if error:
        entry["error"] = error
    logger.info("mcp_tool_call", extra={"custom_dimensions": entry})


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
    feature disabled).  API errors are logged but do **not** block the request —
    availability of the safety service is not a hard runtime dependency.

    Call this *before* regex / whitelist validation to catch injection patterns
    that are semantically harmful but syntactically valid::

        check_content_safety(symbol)   # defense-in-depth
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


# ---------------------------------------------------------------------------
# Injection Pattern Detection (MCP-05: Command Injection) — Camp 3 I/O Security
# ---------------------------------------------------------------------------

# Organized by OWASP MCP risk category; mirrors camp3-io-security/injection_patterns.py
_INJECTION_PATTERNS: dict[str, list[tuple[str, str]]] = {
    # Shell / OS command injection
    "shell_injection": [
        (r"[;&|`$]", "shell metacharacter"),
        (r"(?i)\b(eval|exec|system|popen|subprocess|os\.system|__import__)\s*[\(\[]", "code execution call"),
        (r"\$\(|\$\{|\`", "command substitution"),
    ],
    # SQL injection
    "sql_injection": [
        (r"(?i)\b(union\s+select|drop\s+table|insert\s+into|delete\s+from|update\s+\w+\s+set|exec\s+xp_)\b", "SQL injection keyword"),
        (r"(?i)(--\s*$|;\s*(drop|select|delete|insert|update)\b)", "SQL comment/statement termination"),
    ],
    # Path traversal
    "path_traversal": [
        (r"\.\./|\.\.\\\\", "path traversal sequence"),
        (r"(?i)(%2e%2e[/%5c]|%252e%252e)", "URL-encoded traversal"),
        (r"(?i)(/etc/(passwd|shadow|hosts)|c:\\\\windows\\\\system32)", "sensitive system path"),
    ],
    # General / template injection
    "general_injection": [
        (r"<script[^>]*>", "script tag injection"),
        (r"\x00", "null byte injection"),
        (r"(?i)(<\?php|<%=|\{\{.*\}\})", "template/server-side injection"),
    ],
}


def check_injection_patterns(text: str) -> None:
    """Detect technical injection attacks in tool input text.

    Covers OWASP MCP-05 (Command Injection): shell metacharacters, SQL keywords,
    path traversal, null bytes, and template injection patterns.  This is a
    fast, zero-dependency first-pass check; ``check_content_safety`` adds
    semantic depth on top.

    Raises ``ValueError`` on detection.  No-op for empty text.
    """
    if not text:
        return
    for category, patterns in _INJECTION_PATTERNS.items():
        for pattern, description in patterns:
            if re.search(pattern, text, re.MULTILINE):
                log_security_event(
                    SecurityEventType.INJECTION_BLOCKED,
                    category=category,
                    message=f"Injection blocked: {description}",
                    severity="WARNING",
                    extra_dimensions={"injection_type": category, "description": description},
                )
                raise ValueError(f"Input rejected: detected {description} ({category})")


# ---------------------------------------------------------------------------
# Prompt Shields — jailbreak / indirect injection detection (Camp 3 I/O)
# ---------------------------------------------------------------------------

_shield_token_cache: dict[str, Any] = {"token": None, "expires_at": 0.0}


def check_prompt_shields(text: str) -> None:
    """Detect prompt injection / jailbreak attacks via Azure Content Safety Prompt Shields.

    Calls the ``/contentsafety/text:shieldPrompt`` REST endpoint (api-version=2024-09-01).
    No-op when ``AZURE_CONTENT_SAFETY_ENDPOINT`` is not configured.
    Fails open on any API error — the service is defense-in-depth, not a hard gate.
    """
    endpoint = os.getenv("AZURE_CONTENT_SAFETY_ENDPOINT", "").strip()
    if not endpoint:
        return
    try:
        from azure.identity import DefaultAzureCredential
        now = time.monotonic()
        if not _shield_token_cache["token"] or now >= _shield_token_cache["expires_at"]:
            cred = DefaultAzureCredential()
            tok = cred.get_token("https://cognitiveservices.azure.com/.default")
            _shield_token_cache["token"] = tok.token
            # expire 5 min before actual expiry
            _shield_token_cache["expires_at"] = now + max(tok.expires_on - time.time() - 300, 60)

        url = f"{endpoint.rstrip('/')}/contentsafety/text:shieldPrompt?api-version=2024-09-01"
        resp = httpx.post(
            url,
            json={"userPrompt": text, "documents": []},
            headers={"Authorization": f"Bearer {_shield_token_cache['token']}", "Content-Type": "application/json"},
            timeout=10,
        )
        if resp.status_code == 200:
            if resp.json().get("userPromptAnalysis", {}).get("attackDetected"):
                log_security_event(
                    SecurityEventType.INJECTION_BLOCKED,
                    category="prompt_injection",
                    message="Injection blocked: prompt injection attack detected by Prompt Shields",
                    severity="WARNING",
                    extra_dimensions={"injection_type": "prompt_injection"},
                )
                raise ValueError("Input rejected: prompt injection attack detected (Prompt Shields)")
        else:
            logger.warning("Prompt Shields API returned %s (failing open)", resp.status_code)
    except ValueError:
        raise
    except Exception as exc:
        logger.warning("Prompt Shields check failed (non-blocking): %s", exc)


# ---------------------------------------------------------------------------
# Output Credential Scanning (MCP-03, MCP-10) — Camp 3 I/O Security
# ---------------------------------------------------------------------------

# Regex patterns for known credential formats — mirrors camp3-io-security/credential_scanner.py
_CREDENTIAL_PATTERNS: list[tuple[str, str]] = [
    # API keys
    (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']?([a-zA-Z0-9_-]{20,})["\']?', r'\1=[REDACTED-API_KEY]'),
    # Generic secrets / tokens
    (r'(?i)(secret|token|auth[_-]?token)\s*[=:]\s*["\']?([a-zA-Z0-9_-]{16,})["\']?', r'\1=[REDACTED-SECRET]'),
    # Passwords
    (r'(?i)(password|passwd|pwd)\s*[=:]\s*["\']?([^\s"\'{]{8,})["\']?', r'\1=[REDACTED-PASSWORD]'),
    # Bearer JWT in text
    (r'(?i)bearer\s+([a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)', 'Bearer [REDACTED-JWT]'),
    # Bare JWT pattern (eyJ...)
    (r'\b(eyJ[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]*\.[a-zA-Z0-9_-]+)\b', '[REDACTED-JWT]'),
    # Azure Storage connection string key
    (r'(?i)(AccountKey\s*=\s*)([a-zA-Z0-9+/=]{44,})', r'\1[REDACTED-AZURE_STORAGE_KEY]'),
    # GitHub PAT / OAuth tokens
    (r'\b(ghp_[a-zA-Z0-9]{36})\b', '[REDACTED-GITHUB_PAT]'),
    (r'\b(gho_[a-zA-Z0-9]{36})\b', '[REDACTED-GITHUB_OAUTH]'),
    # Private key headers
    (r'-----BEGIN\s+(?:[A-Z]+\s+)?PRIVATE KEY-----', '[REDACTED-PRIVATE_KEY]'),
    # Client secrets / access keys
    (r'(?i)(client[_-]?secret|access[_-]?key)\s*[=:]\s*["\']?([a-zA-Z0-9+/=_-]{16,})["\']?', r'\1=[REDACTED-SECRET]'),
]

_ENTROPY_THRESHOLD: float = 4.5
_MIN_SECRET_LEN: int = 20
_MAX_SECRET_LEN: int = 200


def _calculate_entropy(text: str) -> float:
    """Shannon entropy of *text*; values above 4.5 indicate random / secret data."""
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for c in text:
        freq[c] = freq.get(c, 0) + 1
    n = len(text)
    return -sum((count / n) * math.log2(count / n) for count in freq.values())


def scan_output_credentials(text: str) -> str:
    """Scan tool output for accidentally leaked credentials and redact them.

    Two-phase approach matching camp3-io-security/credential_scanner.py:

    1. Regex patterns for known credential formats (API keys, JWTs, storage
       keys, GitHub tokens, passwords).
    2. Shannon entropy analysis (threshold 4.5) to catch unknown high-entropy
       secrets that don't match a known pattern.

    Returns sanitised text.  Logs a ``WARNING`` for every credential found so
    security teams can trace the upstream data source.
    Addresses OWASP MCP-03 (Tool Poisoning) and MCP-10 (Context Over-Sharing).
    """
    if not text:
        return text

    redacted = text
    _cred_count: int = 0

    # Phase 1: known pattern regex
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        try:
            if re.search(pattern, redacted, re.MULTILINE):
                logger.warning("Credential pattern found in tool output (pattern=%.60s)", pattern)
                _cred_count += 1
            redacted = re.sub(pattern, replacement, redacted, flags=re.MULTILINE)
        except re.error:
            continue

    # Phase 2: entropy analysis for unknown secrets
    for match in re.finditer(
        r'\b[a-zA-Z0-9+/=_-]{' + str(_MIN_SECRET_LEN) + ',' + str(_MAX_SECRET_LEN) + r'}\b',
        redacted,
    ):
        candidate = match.group()
        if "[REDACTED" in candidate:
            continue
        entropy = _calculate_entropy(candidate)
        has_digits = any(c.isdigit() for c in candidate)
        has_upper = any(c.isupper() for c in candidate)
        has_lower = any(c.islower() for c in candidate)
        if entropy >= _ENTROPY_THRESHOLD and (has_digits or (has_upper and has_lower)):
            logger.warning(
                "High-entropy string in tool output redacted (len=%d entropy=%.2f)",
                len(candidate), entropy,
            )
            _cred_count += 1
            redacted = redacted.replace(candidate, "[REDACTED-HIGH_ENTROPY]", 1)

    if _cred_count:
        log_security_event(
            SecurityEventType.CREDENTIAL_DETECTED,
            category="credential_exposure",
            message=f"Credentials redacted in tool output: {_cred_count} item(s)",
            severity="WARNING",
            extra_dimensions={"credential_count": _cred_count},
        )

    return redacted


# ---------------------------------------------------------------------------
# Protected Resource Metadata — RFC 9728 (MCP OAuth 2.1 auto-discovery)
# ---------------------------------------------------------------------------

class PRMAuthenticateMiddleware(BaseHTTPMiddleware):
    """Add RFC 9728 WWW-Authenticate header on 401/403 responses.

    On 401: ``Bearer resource_metadata="<prm_url>"``
    On 403: ``Bearer error="insufficient_scope", resource_metadata="<prm_url>"``

    Enables OAuth 2.1-aware MCP clients (e.g. VS Code) to auto-discover the
    authorization server and initiate the token flow without manual configuration.
    Addresses OWASP MCP-01 (Token Mismanagement) and MCP-07 (Insufficient Auth).
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)

        if response.status_code not in (401, 403):
            return response

        # Build the PRM discovery URL
        if RESOURCE_URL:
            base_url = RESOURCE_URL.rstrip("/")
        else:
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("x-forwarded-host", request.url.netloc)
            base_url = f"{scheme}://{host}"
        prm_url = f"{base_url}/.well-known/oauth-protected-resource"

        # Drain the body before recreating the response (headers may be immutable)
        body = b""
        async for chunk in response.body_iterator:
            body += chunk

        new_response = Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        if response.status_code == 401:
            existing = response.headers.get("WWW-Authenticate", "")
            if existing and "resource_metadata" not in existing:
                www_auth = f'{existing}, resource_metadata="{prm_url}"'
            else:
                www_auth = f'Bearer resource_metadata="{prm_url}"'
        else:  # 403 — insufficient scope per RFC 6750 Section 3.1
            www_auth = (
                f'Bearer error="insufficient_scope", resource_metadata="{prm_url}"'
            )
        new_response.headers["WWW-Authenticate"] = www_auth
        return new_response


def make_prm_app(mcp_server, *, scopes: list[str] | None = None):
    """Wrap a FastMCP server with RFC 9728 PRM support.

    Adds three layers on top of the base MCP Starlette app:
    1. ``/.well-known/oauth-protected-resource`` — PRM discovery endpoint
    2. ``PRMAuthenticateMiddleware`` — injects WWW-Authenticate on 401/403
    3. ``CORSMiddleware`` — allows cross-origin PRM preflight (public metadata)

    Parameters
    ----------
    mcp_server  : FastMCP instance
    scopes      : short scope names (e.g. ``["portfolio.read"]``); expanded to
                  ``api://<MCP_CLIENT_ID>/<scope>`` in the PRM document.
    """
    app = mcp_server.http_app(stateless_http=True)

    async def prm_endpoint(request):
        """Return Protected Resource Metadata per RFC 9728."""
        if RESOURCE_URL:
            resource = RESOURCE_URL.rstrip("/")
        else:
            scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
            host = request.headers.get("x-forwarded-host", request.url.netloc)
            resource = f"{scheme}://{host}"

        metadata: dict = {
            "resource": resource,
            "bearer_methods_supported": ["header"],
            "token_formats_supported": ["jwt"],
        }
        if ENTRA_TENANT_ID:
            metadata["authorization_servers"] = [
                f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
            ]
        if scopes and MCP_CLIENT_ID:
            metadata["scopes_supported"] = [
                f"api://{MCP_CLIENT_ID}/{s}" for s in scopes
            ]
        elif scopes:
            metadata["scopes_supported"] = scopes
        return JSONResponse(metadata)

    # CORS outermost — OPTIONS preflight must be answered before auth middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],      # PRM endpoint is public, unauthenticated metadata
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.add_middleware(PRMAuthenticateMiddleware)
    # Insert before existing routes so it takes precedence
    app.routes.insert(0, Route("/.well-known/oauth-protected-resource", prm_endpoint))
    return app
