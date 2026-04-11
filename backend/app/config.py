# ============================================================
# Application configuration using Pydantic Settings
# Reads from environment variables (set by azd / Container Apps)
# Reference: https://learn.microsoft.com/en-us/azure/container-apps/environment-variables
# ============================================================

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Azure Managed Identity
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
    azure_cosmos_sessions_container: str = "chat-sessions"  # Per-user chat session history
    azure_cosmos_key: str = ""  # Leave empty to use Managed Identity

    # Azure AI Search — RAG over research documents
    # Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search
    azure_search_endpoint: str
    azure_search_index_name: str = "portfolio-research"
    azure_search_api_key: str = ""  # Leave empty to use Managed Identity

    # Observability — Azure Monitor
    applicationinsights_connection_string: str = ""
    enable_instrumentation: bool = True
    enable_sensitive_data: bool = False  # Never true in production

    # Private MCP server URLs (internal Container Apps FQDNs)
    yahoo_mcp_url: str = "http://localhost:8001"
    portfolio_mcp_url: str = "http://localhost:8002"
    mcp_auth_token: str = "dev-portfolio-mcp-token"  # Shared bearer token for internal MCP servers

    # Remote hosted MCP server — Alpha Vantage (economic indicators, stocks, fundamentals, commodities)
    # Endpoint: https://mcp.alphavantage.co/mcp?apikey=<key>  — no local server needed
    alphavantage_mcp_url: str = "https://mcp.alphavantage.co/mcp"
    alphavantage_api_key: str = ""

    # Entra authentication
    entra_tenant_id: str = ""
    entra_client_id: str = ""  # Frontend SPA app registration
    entra_backend_client_id: str = ""  # Backend API app registration

    # Foundry agent names (created via scripts/setup-foundry.py)
    market_intel_agent_name: str = "portfolio-market-intel"
    portfolio_data_agent_name: str = "portfolio-data-agent"
    economic_data_agent_name: str = "portfolio-economic-agent"
    private_data_agent_name: str = "portfolio-private-data-agent"

    # Bing Grounding connection ID (Foundry project connection for Grounding with Bing Search)
    # Set to the connection_id of your Bing resource in the Foundry project.
    # Leave empty to skip Bing grounding (market_intel_agent falls back to model knowledge).
    bing_connection_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
