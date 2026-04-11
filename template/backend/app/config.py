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

    @property
    def entra_audience(self) -> str:
        """JWT audience = the backend API app registration client ID."""
        return self.entra_backend_client_id

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
