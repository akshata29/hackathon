# ============================================================
# Application configuration — TEMPLATE VERSION
# Copy this file to your project's backend/app/config.py and
# fill in the DOMAIN-SPECIFIC section for your use-case.
#
# The CORE INFRASTRUCTURE section is required by app/core/* and
# must NOT be removed or renamed.
# ============================================================

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ==================================================================
    # CORE INFRASTRUCTURE SETTINGS  (do not remove or rename)
    # Required by app/core/* — auth, observability, session management,
    # and Agent Framework wiring all depend on these fields.
    # ==================================================================

    # Azure Managed Identity client ID (optional; leave empty in local dev)
    azure_client_id: str = ""

    # Azure AI Foundry project endpoint
    # Format: https://<resource>.services.ai.azure.com/api/projects/<project>
    foundry_project_endpoint: str
    foundry_model: str = "gpt-4o"

    # Azure Cosmos DB — conversation history + workflow checkpoints
    azure_cosmos_endpoint: str
    azure_cosmos_database_name: str = "my-app-db"        # TODO: rename for your use-case
    azure_cosmos_container_name: str = "conversations"
    azure_cosmos_checkpoints_container: str = "workflow-checkpoints"
    azure_cosmos_sessions_container: str = "chat-sessions"
    azure_cosmos_key: str = ""  # Leave empty to use Managed Identity

    # Azure AI Search — RAG over your knowledge base documents
    azure_search_endpoint: str
    azure_search_index_name: str = "my-app-knowledge"    # TODO: rename for your use-case
    azure_search_api_key: str = ""  # Leave empty to use Managed Identity

    # Observability — Azure Monitor + OpenTelemetry
    applicationinsights_connection_string: str = ""
    enable_instrumentation: bool = True
    enable_sensitive_data: bool = False  # Never true in production
    otel_service_name: str = "my-app-backend"            # TODO: rename for your use-case

    # Entra ID authentication
    entra_tenant_id: str = ""
    entra_client_id: str = ""        # Frontend SPA app registration
    entra_backend_client_id: str = ""  # Backend API app registration

    # OBO (On-Behalf-Of) token exchange settings
    # entra_client_secret is used by the backend to perform OBO exchanges.
    # Store the actual value in Key Vault; reference it here for local dev only.
    entra_client_secret: str = ""    # api://<backend-client-id> credential

    # Add one field per downstream MCP server your agents connect to.
    # Each OBO-issued token will have the corresponding MCP client ID as
    # its audience.  The scope name (e.g. "portfolio.read") is configured
    # per-agent in your build_tools() call.
    # Example:
    #   my_mcp_client_id: str = ""   # api://<my-mcp-client-id>

    @property
    def entra_audience(self) -> str:
        """JWT audience = the backend API app registration client ID."""
        return self.entra_backend_client_id

    # Frontend origin — used for CORS and post-OAuth redirects back to the SPA.
    # In production set this to your Static Web App URL.
    frontend_url: str = "http://localhost:5173"

    # Additional CORS allowed origins — comma-separated.
    # frontend_url above is always included. Add staging/preview URLs here.
    allowed_cors_origins: str = ""

    # ── GitHub OAuth App  (Pattern 2: vendor OAuth per-user token) ────────────
    # Create an OAuth App at: https://github.com/settings/developers
    # Homepage URL:  <your frontend URL>
    # Callback URL:  <backend URL>/api/auth/github/callback
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""   # Store in Key Vault in production
    github_oauth_redirect_uri: str = "http://localhost:8000/api/auth/github/callback"

    # Demo / Cross-IDP mode helpers (local dev only)
    # mock_oidc_url: URL of the mock Okta-like OIDC server (Option B/C demos)
    # okta_proxy_url: URL of the Okta->MCP proxy for Option C demo
    mock_oidc_url: str = "http://localhost:8889"
    okta_proxy_url: str = "http://localhost:8003"

    # ==================================================================
    # DOMAIN-SPECIFIC SETTINGS
    # Replace everything below with your own configuration variables.
    #
    # Examples of what to add here:
    #   - MCP server URLs for your private data sources
    #   - API keys for external services your agents use
    #   - Foundry agent names (created via your setup-foundry.py script)
    #   - Feature flags specific to your domain
    #
    # Coding prompt: See template/docs/coding-prompts/README.md > Step 1
    # ==================================================================

    # TODO: Add your MCP server URLs
    # my_mcp_url: str = "http://localhost:8001"
    # mcp_auth_token: str = "dev-mcp-token"

    # TODO: Add any external service keys your agents need
    # some_api_key: str = ""

    # TODO: Add Foundry agent names that your setup-foundry.py creates
    # agent_a_name: str = "my-app-agent-a"
    # agent_b_name: str = "my-app-agent-b"

    # TODO: Add A2A remote agent URLs (leave empty to disable)
    # my_a2a_agent_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
