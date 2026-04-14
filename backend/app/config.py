# ============================================================
# Application configuration using Pydantic Settings
# Reads from environment variables (set by azd / Container Apps)
# Reference: https://learn.microsoft.com/en-us/azure/container-apps/environment-variables
#
# Settings are split into two sections:
#   CORE INFRASTRUCTURE — shared by every use-case built from this template.
#     Do not remove or rename core settings; they wire auth, observability,
#     session management, and Agent Framework.
#   DOMAIN-SPECIFIC — specific to the Portfolio Advisor example.
#     When building a new use-case, replace this section with your own vars.
# ============================================================

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ==================================================================
    # CORE INFRASTRUCTURE SETTINGS
    # These are required by app/core/* and must be present in every
    # use-case that builds from this template.
    # ==================================================================

    # Azure Managed Identity client ID (optional; leave empty in local dev)
    azure_client_id: str = ""

    # Azure AI Foundry (Response API v2)
    # Format: https://<resource>.services.ai.azure.com/api/projects/<project>
    foundry_project_endpoint: str
    foundry_model: str = "gpt-4o"

    # Azure Cosmos DB — conversation history + workflow checkpoints
    # Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/conversations
    azure_cosmos_endpoint: str
    azure_cosmos_database_name: str = "portfolio-advisor"
    azure_cosmos_container_name: str = "conversations"
    azure_cosmos_checkpoints_container: str = "workflow-checkpoints"
    azure_cosmos_sessions_container: str = "chat-sessions"
    azure_cosmos_key: str = ""  # Leave empty to use Managed Identity

    # Azure AI Search — RAG over research documents
    # Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search
    azure_search_endpoint: str
    azure_search_index_name: str = "portfolio-research"
    azure_search_api_key: str = ""  # Leave empty to use Managed Identity

    # Observability — Azure Monitor + OpenTelemetry
    applicationinsights_connection_string: str = ""
    enable_instrumentation: bool = True
    enable_sensitive_data: bool = False  # Never true in production
    otel_service_name: str = "portfolio-advisor-backend"  # Override per use-case

    # Entra ID authentication
    entra_tenant_id: str = ""
    entra_client_id: str = ""           # Frontend SPA app registration
    entra_backend_client_id: str = ""   # Backend API app registration (JWT audience)

    # OBO: backend exchanges the user's token for downstream MCP tokens.
    # Store the client secret in Key Vault; read via ENTRA_CLIENT_SECRET env var.
    # Leave empty in local dev — OBO is skipped and static MCP tokens are used.
    entra_client_secret: str = ""

    # MCP server app registration client IDs (audience for OBO-issued tokens).
    # Set these after running scripts/post-provision.ps1 which creates the app regs.
    portfolio_mcp_client_id: str = ""   # api://<id>/portfolio.read
    yahoo_mcp_client_id: str = ""       # api://<id>/market.read

    @property
    def entra_audience(self) -> str:
        """JWT audience = the backend API app registration client ID."""
        return self.entra_backend_client_id

    # ==================================================================
    # DOMAIN-SPECIFIC SETTINGS  (Portfolio Advisor example)
    # When building a new use-case, replace everything below this line
    # with your own domain configuration variables.
    # ==================================================================

    # Private MCP server URLs (internal Container Apps FQDNs)
    yahoo_mcp_url: str = "http://localhost:8001"
    portfolio_mcp_url: str = "http://localhost:8002"
    mcp_auth_token: str = "dev-portfolio-mcp-token"  # Shared bearer token for internal MCP servers

    # Demo / Cross-IDP mode helpers (local dev only)
    # mock_oidc_url: URL of the mock Okta-like OIDC server (Option B/C demos)
    # okta_proxy_url: URL of the Okta→MCP proxy for Option C demo
    mock_oidc_url: str = "http://localhost:8889"
    okta_proxy_url: str = "http://localhost:8003"

    # Remote hosted MCP server — Alpha Vantage (economic indicators, stocks, fundamentals)
    # Endpoint: https://mcp.alphavantage.co/mcp?apikey=<key>  — no local server needed
    alphavantage_mcp_url: str = "https://mcp.alphavantage.co/mcp"
    alphavantage_api_key: str = ""

    # Foundry agent names (created via scripts/setup-foundry.py)
    market_intel_agent_name: str = "portfolio-market-intel"
    portfolio_data_agent_name: str = "portfolio-data-agent"
    economic_data_agent_name: str = "portfolio-economic-agent"
    private_data_agent_name: str = "portfolio-private-data-agent"

    # Bing Grounding connection ID (Foundry project connection for Grounding with Bing Search)
    # Set to the connection_id of your Bing resource in the Foundry project.
    # Leave empty to skip Bing grounding (market_intel_agent falls back to model knowledge).
    bing_connection_id: str = ""

    # Frontend origin — used for CORS and post-OAuth redirects back to the SPA.
    # In production set this to your Static Web App URL (e.g. https://xxx.azurestaticapps.net).
    frontend_url: str = "http://localhost:5173"

    # Additional CORS allowed origins — comma-separated.
    # frontend_url above is always included. Add staging/preview URLs here.
    # e.g. "https://staging.myapp.com,https://preview.myapp.com"
    allowed_cors_origins: str = ""

    # A2A agent URLs
    # ESG Advisor: LangChain ReAct agent served via A2A protocol (a2a-agents/esg-advisor/)
    # Leave empty to disable; the registry build loop skips None-returning agents.
    esg_advisor_url: str = ""

    # ── GitHub OAuth App  (Pattern 2: vendor OAuth per-user token) ────────────
    # Create an OAuth App at: https://github.com/settings/developers
    # Homepage URL:  <your frontend URL>
    # Callback URL:  <backend URL>/api/auth/github/callback
    # -------------------------------------------------------------------------
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""   # Store in Key Vault in production
    github_oauth_redirect_uri: str = "http://localhost:8000/api/auth/github/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
