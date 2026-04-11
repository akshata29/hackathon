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
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "")
_STATIC_DEV_TOKEN: str = os.getenv("MCP_AUTH_TOKEN", "dev-yahoo-mcp-token")

_WELL_KNOWN_OPENID = (
    "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
)

_jwks_uri: str | None = None
_jwks_cache: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# JWKS helpers
# ---------------------------------------------------------------------------

async def _get_jwks() -> dict[str, Any]:
    global _jwks_uri, _jwks_cache
    if _jwks_cache:
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

    return _jwks_cache  # type: ignore[return-value]


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

class EntraTokenVerifier:
    """FastMCP TokenVerifier that validates Entra ID Bearer tokens via JWKS.

    Register as ``mcp = FastMCP(auth=EntraTokenVerifier())``.

    Production: validates the OBO token the backend sends.
    Dev mode: falls back to static token comparison.
    """

    async def verify_token(self, token: str) -> dict[str, Any] | None:
        if not ENTRA_TENANT_ID:
            if token == _STATIC_DEV_TOKEN:
                return {"sub": "backend-service", "dev_mode": True}
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
            return claims

        except Exception as exc:
            logger.warning("Token verification failed: %s", exc)
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
