# ============================================================
# Entra ID (Azure AD) JWT validation middleware
# Validates Bearer tokens from MSAL auth in the React SPA
#
# CORE SERVICE — do not add domain-specific logic here.
# ============================================================

import logging
from functools import lru_cache
from typing import Any

import httpx
from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwk, jwt
from jose.utils import base64url_decode

logger = logging.getLogger(__name__)
security_scheme = HTTPBearer(auto_error=False)


class EntraJWTValidator:
    """Validates Azure AD / Entra ID JWT access tokens using JWKS."""

    WELL_KNOWN_OPENID = (
        "https://login.microsoftonline.com/{tenant_id}/v2.0/.well-known/openid-configuration"
    )

    def __init__(self, tenant_id: str, audience: str) -> None:
        self._tenant_id = tenant_id
        self._audience = audience
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
        try:
            # Decode header without verification to get kid
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
        except JWTError as exc:
            logger.warning("JWT header decode failed: %s", exc)
            raise HTTPException(status_code=401, detail="Invalid token header") from exc

        jwks = await self._get_jwks()
        # Find matching key
        rsa_key: dict[str, str] = {}
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e")}
                break

        if not rsa_key:
            # Invalidate JWKS cache so next request refetches (key rotation)
            self._jwks_cache = None
            raise HTTPException(status_code=401, detail="Public key not found")

        issuer = f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                audience=self._audience,
                issuer=issuer,
            )
        except JWTError as exc:
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
