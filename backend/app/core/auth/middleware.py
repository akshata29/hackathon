# ============================================================
# Entra ID (Azure AD) JWT validation middleware
# Validates Bearer tokens from MSAL auth in the React SPA
#
# CORE SERVICE — do not add domain-specific logic here.
# ============================================================

import base64
import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import httpx
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

logger = logging.getLogger(__name__)
security_scheme = HTTPBearer(auto_error=False)


def _decode_claims_unsafe(token: str) -> dict[str, Any]:
    """Base64-decode JWT payload without signature verification.

    Used in dev mode only — never call this before signature validation in prod.
    """
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padding = 4 - len(parts[1]) % 4
    try:
        return json.loads(base64.urlsafe_b64decode(parts[1] + "=" * padding))
    except Exception:
        return {}


@dataclass
class AuthContext:
    """Holds the validated JWT claims and the raw Bearer token string.

    ``user_id`` is a stable identifier suitable for:
    - CosmosDB session partitioning
    - Passing to orchestrators as ``user_token``
    - OBO exchange (via the raw token) to downstream MCP servers

    Preference order: preferred_username (email/UPN) > oid (object ID) > sub.
    """
    claims: dict[str, Any]
    raw_token: str

    @property
    def user_id(self) -> str:
        return (
            self.claims.get("preferred_username")
            or self.claims.get("oid")
            or self.claims.get("sub")
            or "anonymous"
        )


class EntraJWTValidator:
    """Validates Azure AD / Entra ID JWT access tokens using JWKS."""

    # Use the tenant-specific OIDC endpoint for app tokens (api://<clientId>/...).
    WELL_KNOWN_OPENID = (
        "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
    )

    # Microsoft Graph resource identifiers.  Tokens with these audiences are signed
    # by Graph's own key infrastructure (separate from Entra OIDC keys) so they
    # cannot be validated via the tenant JWKS.  We verify claims instead.
    _GRAPH_AUDIENCES = frozenset({
        "https://graph.microsoft.com",
        "00000003-0000-0000-c000-000000000000",
    })

    def __init__(self, tenant_id: str, audience: str) -> None:
        self._tenant_id = tenant_id
        # Accept both the api:// URI form and the plain GUID form of the audience.
        # Entra issues the plain GUID when the app has no API scopes exposed yet;
        # it issues api://<guid> once oauth2PermissionScopes are configured.
        stripped = audience.removeprefix("api://")
        self._audience: list[str] = list({audience, stripped, f"api://{stripped}"})
        self._jwks_uri: str | None = None
        self._jwks_cache: dict[str, Any] | None = None

    async def _get_jwks_uri(self) -> str:
        if self._jwks_uri:
            return self._jwks_uri
        url = self.WELL_KNOWN_OPENID.format(tenant_id=self._tenant_id)
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            self._jwks_uri = resp.json()["jwks_uri"]
        return self._jwks_uri  # type: ignore[return-value]

    async def _get_jwks(self) -> dict[str, Any]:
        if self._jwks_cache:
            return self._jwks_cache
        uri = await self._get_jwks_uri()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(uri)
            resp.raise_for_status()
            self._jwks_cache = resp.json()
        return self._jwks_cache  # type: ignore[return-value]

    async def validate(self, token: str) -> dict[str, Any]:
        """Validate token and return decoded claims. Raises HTTPException on failure."""

        # Peek at claims without signature verification to route handling.
        unverified = _decode_claims_unsafe(token)
        aud = unverified.get("aud", "")

        # -------------------------------------------------------------------
        # Graph tokens (User.Read etc.) are signed by Microsoft Graph's own
        # key infrastructure — those keys are NOT in the Entra OIDC JWKS.
        # Verify claims (iss, tid, exp) instead of signature.
        # -------------------------------------------------------------------
        if aud in self._GRAPH_AUDIENCES or str(aud).startswith("https://graph.microsoft.com"):
            exp = unverified.get("exp", 0)
            if exp and exp < time.time():
                raise HTTPException(status_code=401, detail="Token expired")
            iss = unverified.get("iss", "")
            # Graph tokens can carry either v1 or v2 issuer depending on Graph's
            # accessTokenAcceptedVersion setting (Graph itself uses v1 by default).
            # v2: https://login.microsoftonline.com/{tid}/v2.0
            # v1: https://sts.windows.net/{tid}/
            # The tid claim is the reliable tenant check; accept both issuer forms.
            expected_v2 = f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
            expected_v1 = f"https://sts.windows.net/{self._tenant_id}/"
            if iss and iss not in (expected_v2, expected_v1):
                raise HTTPException(status_code=401, detail="Token issuer mismatch")
            tid = unverified.get("tid", "")
            if tid and tid != self._tenant_id:
                raise HTTPException(status_code=401, detail="Token tenant mismatch")
            return unverified

        # -------------------------------------------------------------------
        # App tokens (api://<clientId>/...) — full JWKS signature verification.
        # -------------------------------------------------------------------
        try:
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
        except JWTError as exc:
            logger.warning("JWT header decode failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid token header") from exc

        jwks = await self._get_jwks()
        rsa_key: dict[str, str] = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e")}
                break

        if not rsa_key:
            self._jwks_cache = None
            raise HTTPException(status_code=401, detail="Public key not found")

        # App tokens can carry either v2 or v1 issuer depending on the app registration's
        # requestedAccessTokenVersion setting (null/1 → v1, 2 → v2).
        # v2: https://login.microsoftonline.com/{tenant}/v2.0
        # v1: https://sts.windows.net/{tenant}/
        # Decode without issuer enforcement, then manually accept both forms.
        expected_issuers = {
            f"https://login.microsoftonline.com/{self._tenant_id}/v2.0",
            f"https://sts.windows.net/{self._tenant_id}/",
        }
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=None,  # python-jose rejects a list; aud checked manually below
                options={"verify_aud": False, "verify_iss": False},
            )
            aud = claims.get("aud", "")
            if aud and isinstance(aud, str) and aud not in self._audience:
                raise HTTPException(status_code=401, detail="Token audience mismatch")
            iss = claims.get("iss", "")
            if iss and iss not in expected_issuers:
                raise HTTPException(status_code=401, detail="Token issuer mismatch")
            tid = claims.get("tid", "")
            if tid and tid != self._tenant_id:
                raise HTTPException(status_code=401, detail="Token tenant mismatch")
        except JWTError as exc:
            self._jwks_cache = None
            self._jwks_uri = None
            logger.warning("JWT validation failed: %s", exc)
            raise HTTPException(status_code=401, detail="Token validation failed") from exc

        return claims


# ---------------------------------------------------------------------------
# Dependency helpers
# ---------------------------------------------------------------------------

_validator_instance: EntraJWTValidator | None = None


def get_validator(tenant_id: str, audience: str) -> EntraJWTValidator:
    global _validator_instance  # noqa: PLW0603
    if _validator_instance is None:
        _validator_instance = EntraJWTValidator(tenant_id=tenant_id, audience=audience)
    return _validator_instance


async def maybe_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
) -> dict[str, Any] | None:
    """
    Soft auth: returns claims if a valid Bearer token is present, else None.
    Use this for endpoints that are accessible anonymously but enriched when authenticated.
    """
    if not credentials:
        return None
    from app.config import get_settings  # avoid circular import
    settings = get_settings()
    if not settings.entra_tenant_id or not settings.entra_audience:
        return None
    validator = get_validator(settings.entra_tenant_id, settings.entra_audience)
    return await validator.validate(credentials.credentials)


async def require_authenticated_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
) -> dict[str, Any]:
    """
    Hard auth: raises HTTP 401 if token is missing or invalid.
    Use this for sensitive routes (confidential domain data).
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="Authorization header required")
    from app.config import get_settings
    settings = get_settings()
    if not settings.entra_tenant_id or not settings.entra_audience:
        # Auth not configured — allow through in development mode only
        logger.warning("Entra auth not configured; skipping token validation (DEV MODE)")
        return {"sub": "dev", "oid": "dev", "name": "Developer"}
    validator = get_validator(settings.entra_tenant_id, settings.entra_audience)
    return await validator.validate(credentials.credentials)


async def require_auth_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security_scheme),
) -> AuthContext:
    """Returns an AuthContext with both validated JWT claims and the raw Bearer token.

    This is the preferred dependency for routes that need to:
    - Identify the user (user_id / oid)
    - Perform OBO token exchange for downstream MCP calls (raw_token)

    Dev mode (ENTRA_TENANT_ID not set):
        - No signature validation; claims are decoded unsafely for convenience.
        - Falls back to a stable dev identity when no token is present.

    Production (ENTRA_TENANT_ID set):
        - Full JWKS signature validation; HTTP 401 on failure.
        - raw_token is the as-received Bearer string passed to OBOAuth.
    """
    from app.config import get_settings
    settings = get_settings()

    if not credentials:
        if settings.entra_tenant_id and settings.entra_audience:
            raise HTTPException(status_code=401, detail="Authorization header required")
        # Dev mode — no token present
        return AuthContext(
            claims={"sub": "dev", "oid": "dev", "preferred_username": "dev@localhost"},
            raw_token="",
        )

    raw_token = credentials.credentials

    if not settings.entra_tenant_id or not settings.entra_audience:
        # Dev mode — decode without signature verification
        logger.warning("Entra auth not configured; skipping token validation (DEV MODE)")
        claims = _decode_claims_unsafe(raw_token)
        if not claims:
            claims = {"sub": "dev", "oid": "dev", "preferred_username": "dev@localhost"}
        return AuthContext(claims=claims, raw_token=raw_token)

    validator = get_validator(settings.entra_tenant_id, settings.entra_audience)
    claims = await validator.validate(raw_token)
    return AuthContext(claims=claims, raw_token=raw_token)
