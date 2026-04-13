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

    # Last resort: raise in production (ENTRA_TENANT_ID set); ephemeral token in dev only.
    # An ephemeral random token would silently break auth in production environments.
    if os.getenv("ENTRA_TENANT_ID"):
        raise RuntimeError(
            "MCP_AUTH_TOKEN is not set and Key Vault lookup failed. "
            "Set the MCP_AUTH_TOKEN environment variable or configure AZURE_KEYVAULT_ENDPOINT "
            "with a Managed Identity that has Key Vault Secrets User rights."
        )
    import secrets as _secrets
    _cached_token = _secrets.token_urlsafe(32)
    logger.warning(
        "MCP_AUTH_TOKEN not configured. Generated ephemeral token (DEV ONLY). "
        "Set MCP_AUTH_TOKEN env var or configure AZURE_KEYVAULT_ENDPOINT."
    )
    return _cached_token
