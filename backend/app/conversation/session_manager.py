# ============================================================
# Conversation / Session Manager
# Uses CosmosHistoryProvider for durable multi-turn conversation persistence
# Reference: https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/conversations/cosmos_history_provider.py
# Reference: https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/conversations/cosmos_history_provider_sessions.py
# ============================================================

import logging
from typing import AsyncContextManager

from azure.identity.aio import DefaultAzureCredential

from app.config import Settings

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages per-user conversation sessions backed by Azure Cosmos DB.

    Key design: session_id = f"{user_id}:{conversation_id}" ensures
    per-user isolation at the Cosmos DB partition level.

    Reference: CosmosHistoryProvider supports:
      - list_sessions() to enumerate all sessions for a user
      - Per-tenant session isolation via partition key
      - Automatic 30-day TTL (configured in cosmosdb.bicep)
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._credential: DefaultAzureCredential | None = None

    async def get_credential(self) -> DefaultAzureCredential:
        if self._credential is None:
            self._credential = DefaultAzureCredential(
                managed_identity_client_id=self._settings.azure_client_id or None
            )
        return self._credential

    def make_history_provider(self) -> AsyncContextManager:
        """
        Create a CosmosHistoryProvider context manager.

        Usage:
            async with session_manager.make_history_provider() as history_provider:
                async with Agent(client=client, context_providers=[history_provider]) as agent:
                    session = agent.create_session()
                    result = await agent.run("query", session=session)
        """
        from agent_framework.azure import CosmosHistoryProvider

        settings = self._settings
        credential = settings.azure_cosmos_key or None

        return CosmosHistoryProvider(
            endpoint=settings.azure_cosmos_endpoint,
            database_name=settings.azure_cosmos_database_name,
            container_name=settings.azure_cosmos_container_name,
            # Uses DefaultAzureCredential if no key provided (Managed Identity)
            credential=credential or DefaultAzureCredential(
                managed_identity_client_id=settings.azure_client_id or None
            ),
        )

    @staticmethod
    def make_session_id(user_id: str, conversation_id: str) -> str:
        """
        Create a deterministic session ID scoped to a user + conversation.

        This ensures Cosmos DB partition isolation between users — a critical
        security boundary for financial data.
        """
        return f"{user_id}:{conversation_id}"
