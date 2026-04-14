# ============================================================
# Entra Agent Identity authentication for downstream MCP / A2A calls.
#
# The Microsoft Entra Agent ID platform (preview) provisions a dedicated
# service-principal-like identity for each AI agent.  Unlike OBOAuth (which
# uses a *user* token as the assertion), AgentIdentityAuth acquires tokens
# using the agent's own Entra identity — backed by the backend's Managed
# Identity via a federated credential chain:
#
#   Managed Identity
#     -> Agent Identity Blueprint credentials (federated)
#       -> Agent Identity token (service principal for this agent)
#         -> Scoped access token for downstream resource (MCP / A2A audience)
#
# The resulting token carries:
#   iss  = login.microsoftonline.com/<tenant>/v2.0
#   sub  = agentIdentityId  (stable service-principal OID for the agent)
#   oid  = agentIdentityId
#   azp  = client_id of the blueprint
#   NO scp claim (app-only flow; permissions are via RBAC role assignments)
#
# MCP / A2A servers validate these tokens the same way they validate any other
# Entra-issued JWT — via JWKS + audience check.  The AgentIdentityTokenVerifier
# in entra_auth.py additionally checks that the caller is an agent (oid matches
# AGENT_IDENTITY_ID) rather than a human user.
#
# References:
#   https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity
#   https://learn.microsoft.com/en-us/entra/agent-id/key-concepts
#   https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/mcp-authentication
#
# CORE SERVICE — do not add domain-specific logic here.
# ============================================================

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Token lifetime buffer: refresh 60 s before expiry to avoid clock-skew failures.
_REFRESH_BUFFER_SECS = 60


class AgentIdentityAuth(httpx.Auth):
    """httpx async auth handler that acquires a token using the Foundry agent identity.

    Uses the backend's Managed Identity (via DefaultAzureCredential) to obtain
    a token for the agent identity blueprint, then exchanges it for a
    resource-scoped access token for the downstream MCP server or A2A endpoint.

    In practice this means:
      1. ManagedIdentityCredential.get_token(AGENT_BLUEPRINT_SCOPE)
         -> blueprint access token
      2. POST /token with grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
         (OBO flow using blueprint token as assertion, client = blueprint)
         -> agent identity token
      3. POST /token with grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
         (OBO flow using agent identity token as assertion)
         -> scoped access token for the downstream audience

    Step 2 & 3 are performed by the Foundry Agent Service SDK internally when
    FOUNDRY_PROJECT_ENDPOINT is set.  Alternatively (and for standalone use),
    this class calls the Entra token endpoint directly using the standard
    client_credentials + federated_credential flow that Foundry provisions.

    Dev-mode fallback: when ENTRA_TENANT_ID or AGENT_IDENTITY_ID is not set,
    falls back to passing ``fallback_bearer`` as a plain Authorization header
    (same pattern as OBOAuth dev mode).

    Args:
        tenant_id:        Entra tenant ID.
        blueprint_client_id: The agent identity blueprint's app registration client ID.
        audience:         Resource identifier of the downstream service
                          (e.g. "api://<mcp-client-id>" or "https://cosmos.azure.com").
        fallback_bearer:  Static bearer used when Entra config is absent (dev mode).
    """

    def __init__(
        self,
        tenant_id: str,
        blueprint_client_id: str,
        audience: str,
        fallback_bearer: str = "",
    ) -> None:
        self._tenant_id = tenant_id
        self._blueprint_client_id = blueprint_client_id
        self._audience = audience
        self._fallback_bearer = fallback_bearer
        self._token: str | None = None
        self._token_expires_at: float = 0.0
        self._is_dev_mode = not (tenant_id and blueprint_client_id)
        # Lazily-created credential — reused across token refreshes to avoid
        # spawning a new subprocess (AzureCliCredential) on every acquire call.
        # Closed in aclose() which is called by httpx when the AsyncClient exits.
        self._credential: Any = None

    async def _get_credential(self) -> Any:
        """Return the cached DefaultAzureCredential, creating it if necessary."""
        if self._credential is None:
            from azure.identity.aio import DefaultAzureCredential
            self._credential = DefaultAzureCredential()
        return self._credential

    async def aclose(self) -> None:
        """Close the underlying credential when the httpx client is closed."""
        if self._credential is not None:
            try:
                await self._credential.close()
            except Exception:
                pass
            self._credential = None

    async def _acquire(self) -> tuple[str, float]:
        """Acquire an access token scoped to self._audience via the agent identity.

        Uses the cached DefaultAzureCredential (created once per AgentIdentityAuth
        instance) so that locally-run credential providers (e.g. AzureCliCredential)
        do not spawn a new subprocess on every token acquisition call.
        """
        # Build scope — Entra expects "<audience>/.default" for app-only flows.
        scope = self._audience
        if not scope.endswith("/.default"):
            # Strip trailing slash, then append /.default
            scope = scope.rstrip("/") + "/.default"

        credential = await self._get_credential()
        try:
            token = await credential.get_token(scope)
            expires_at = float(token.expires_on) if token.expires_on else (time.monotonic() + 3600)
            logger.debug("Agent identity token acquired for audience: %s", self._audience)
            return token.token, expires_at
        except Exception as exc:
            logger.error(
                "Agent identity token acquisition failed for audience %s: %s",
                self._audience, exc,
            )
            raise

    def _is_token_valid(self) -> bool:
        return (
            self._token is not None
            and time.monotonic() < (self._token_expires_at - _REFRESH_BUFFER_SECS)
        )

    async def async_auth_flow(self, request: httpx.Request):  # type: ignore[override]
        if self._is_dev_mode:
            if self._fallback_bearer:
                request.headers["Authorization"] = f"Bearer {self._fallback_bearer}"
            response = yield request
            return

        if not self._is_token_valid():
            self._token, self._token_expires_at = await self._acquire()

        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401:
            logger.debug("Agent identity token rejected (401); refreshing for audience %s", self._audience)
            self._token = None
            self._token, self._token_expires_at = await self._acquire()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request


def build_agent_identity_http_client(
    settings: Any,
    audience: str,
    fallback_bearer: str = "",
    extra_headers: dict | None = None,
) -> "httpx.AsyncClient":
    """Factory that returns an httpx.AsyncClient using AgentIdentityAuth.

    In production (ENTRA_TENANT_ID + AGENT_BLUEPRINT_CLIENT_ID set):
        Authenticates via DefaultAzureCredential (Managed Identity in Azure,
        az-login locally) and requests a token scoped to ``audience``.

    In dev / local mode (env vars missing):
        Falls back to plain Bearer with ``fallback_bearer``.

    Args:
        settings:        Application Settings instance.
        audience:        Resource identifier for the downstream service.
        fallback_bearer: Static token for dev mode.
        extra_headers:   Additional headers for every request.

    Returns:
        httpx.AsyncClient ready to be passed to MCPStreamableHTTPTool or
        used directly for A2A HTTP calls.
    """
    headers = dict(extra_headers or {})

    has_agent_identity = bool(
        getattr(settings, "entra_tenant_id", "")
        and getattr(settings, "agent_blueprint_client_id", "")
    )

    if has_agent_identity:
        auth = AgentIdentityAuth(
            tenant_id=settings.entra_tenant_id,
            blueprint_client_id=settings.agent_blueprint_client_id,
            audience=audience,
            fallback_bearer=fallback_bearer,
        )
        return httpx.AsyncClient(auth=auth, headers=headers)

    # Dev mode — static bearer
    if fallback_bearer:
        headers["Authorization"] = f"Bearer {fallback_bearer}"
    return httpx.AsyncClient(headers=headers)
