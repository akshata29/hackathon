# ============================================================
# Key Vault helper for Yahoo Finance MCP server
# Uses DefaultAzureCredential (Managed Identity in Container Apps)
# Falls back to env var MCP_AUTH_TOKEN in local development
# ============================================================

import os
import logging

logger = logging.getLogger(__name__)

_cached_token: str | None = None


def get_mcp_auth_token() -> str:
    """Retrieve the MCP auth token from Key Vault or environment."""
    global _cached_token  # noqa: PLW0603
    if _cached_token:
        return _cached_token

    # Prefer env var (local dev or pre-loaded by Container Apps secret)
    env_token = os.getenv("MCP_AUTH_TOKEN")
    if env_token:
        _cached_token = env_token
        return _cached_token

    # Attempt Key Vault via Managed Identity
    kv_url = os.getenv("AZURE_KEYVAULT_ENDPOINT")
    if kv_url:
        try:
            from azure.identity import DefaultAzureCredential
            from azure.keyvault.secrets import SecretClient

            client = SecretClient(vault_url=kv_url, credential=DefaultAzureCredential())
            secret = client.get_secret("yahoo-mcp-auth-token")
            _cached_token = secret.value
            return _cached_token  # type: ignore[return-value]
        except Exception as exc:
            logger.warning("Key Vault fetch failed: %s — falling back to default token", exc)

    # Last resort: generate a random token (insecure — dev only warning)
    import secrets as _secrets
    _cached_token = _secrets.token_urlsafe(32)
    logger.warning(
        "MCP_AUTH_TOKEN not configured. Generated ephemeral token (DEV ONLY). "
        "Set MCP_AUTH_TOKEN env var or configure AZURE_KEYVAULT_ENDPOINT."
    )
    return _cached_token
