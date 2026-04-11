# ============================================================
# On-Behalf-Of (OBO) token exchange for downstream MCP servers.
#
# The backend receives a user's Entra ID access token (audience = backend API).
# When calling a confidential MCP server it exchanges that token for a new one
# whose audience is the MCP server's own app registration.  The downstream MCP
# server then validates the OBO token with JWKS, confirming both:
#   - which user is making the request  (oid / preferred_username claim)
#   - which delegated permissions apply (scp claim, e.g. "my-scope.read")
#
# Reference:
#   https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow
#   https://learn.microsoft.com/en-us/python/api/azure-identity/azure.identity.aio.onbehalfofcredential
#
# CORE SERVICE -- do not add domain-specific logic here.
# ============================================================

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OBOAuth(httpx.Auth):
    """httpx async auth handler that performs the OBO token exchange on first use.

    Attach an instance of this class to an ``httpx.AsyncClient`` and it will:
    1. Exchange the user's incoming Bearer token for an OBO token scoped to the
       downstream MCP server's app registration.
    2. Cache the token across requests.
    3. Automatically refresh on HTTP 401 (token expiry / rotation).

    Usage::

        auth = OBOAuth(
            tenant_id=settings.entra_tenant_id,
            client_id=settings.entra_backend_client_id,
            client_secret=settings.entra_client_secret,
            user_assertion=raw_user_token,
            scope=f"api://{settings.my_mcp_client_id}/my-scope.read",
        )
        http_client = httpx.AsyncClient(auth=auth)

    Dev-mode behaviour: if ``user_assertion`` is empty / None, falls back to
    passing the ``fallback_bearer`` as a plain Authorization header (backward
    compat with the static-token dev setup).
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        user_assertion: str,
        scope: str,
        fallback_bearer: str = "",
    ) -> None:
        self._tenant_id = tenant_id
        self._client_id = client_id
        self._client_secret = client_secret
        self._user_assertion = user_assertion
        self._scope = scope
        self._fallback_bearer = fallback_bearer
        self._token: str | None = None
        self._is_dev_mode = not (tenant_id and client_id and client_secret and user_assertion)

    async def _acquire(self) -> str:
        from azure.identity.aio import OnBehalfOfCredential

        credential = OnBehalfOfCredential(
            tenant_id=self._tenant_id,
            client_id=self._client_id,
            client_secret=self._client_secret,
            user_assertion=self._user_assertion,
        )
        try:
            token = await credential.get_token(self._scope)
            logger.debug("OBO token acquired for scope: %s", self._scope)
            return token.token
        except Exception as exc:
            logger.error("OBO token exchange failed for scope %s: %s", self._scope, exc)
            raise
        finally:
            await credential.close()

    async def async_auth_flow(self, request: httpx.Request):  # type: ignore[override]
        if self._is_dev_mode:
            # Dev / local fallback -- use static bearer token
            if self._fallback_bearer:
                request.headers["Authorization"] = f"Bearer {self._fallback_bearer}"
            response = yield request
            return

        if not self._token:
            self._token = await self._acquire()

        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401:
            # Token may have expired -- force one refresh attempt
            logger.debug("OBO token rejected (401); refreshing for scope %s", self._scope)
            self._token = None
            self._token = await self._acquire()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request


def build_obo_http_client(
    settings: Any,
    raw_token: str | None,
    mcp_client_id: str,
    scope_name: str,
    fallback_bearer: str = "",
    extra_headers: dict | None = None,
) -> "httpx.AsyncClient":
    """Factory that returns an httpx.AsyncClient pre-configured for OBO auth.

    In production (all Entra env vars set + non-empty raw_token):
        Uses OBOAuth -- full OBO exchange against Entra.

    In dev mode (missing Entra config or no raw_token):
        Falls back to plain Bearer with ``fallback_bearer`` (the static MCP token).

    Args:
        settings:        Application Settings instance.
        raw_token:       The user's raw Entra Bearer string (from the HTTP request).
        mcp_client_id:   The target MCP server's Entra app registration client ID.
        scope_name:      The OAuth2 scope to request (e.g. "my-scope.read").
        fallback_bearer: Static token used in dev mode.
        extra_headers:   Additional headers to include on every request.

    Returns:
        httpx.AsyncClient ready to be passed to MCPStreamableHTTPTool.
    """
    headers = dict(extra_headers or {})

    has_entra = bool(
        settings.entra_tenant_id
        and settings.entra_backend_client_id
        and settings.entra_client_secret
        and mcp_client_id
        and raw_token
    )

    if has_entra:
        scope = f"api://{mcp_client_id}/{scope_name}"
        auth = OBOAuth(
            tenant_id=settings.entra_tenant_id,
            client_id=settings.entra_backend_client_id,
            client_secret=settings.entra_client_secret,
            user_assertion=raw_token,
            scope=scope,
            fallback_bearer=fallback_bearer,
        )
        return httpx.AsyncClient(auth=auth, headers=headers)

    # Dev mode -- static bearer + optional extra headers (e.g. X-User-Id for RLS)
    if fallback_bearer:
        headers["Authorization"] = f"Bearer {fallback_bearer}"
    return httpx.AsyncClient(headers=headers)
