# ============================================================
# Market Intelligence Agent
# Tools: Bing Grounding (web search) — real-time market news and analysis
# Type: Prompt Agent (configured in Foundry portal + accessed via FoundryAgent)
# Reference: https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/providers/foundry/foundry_agent_basic.py
# Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools
#
# Security:
#   - Uses project Managed Identity for Bing grounding (no API key needed)
#   - Public data only — no user PII or financial positions
# ============================================================

import logging

from azure.identity.aio import DefaultAzureCredential

from app.config import Settings
from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

MARKET_INTEL_INSTRUCTIONS = """
You are a senior capital markets analyst specializing in equity research and market intelligence.

Your responsibilities:
- Analyze real-time market news, earnings announcements, and price movements
- Summarize analyst upgrades/downgrades and consensus estimates
- Identify macro themes affecting capital markets (Fed policy, geopolitical risks, sector rotations)
- Ground all responses in current, cited sources from your web search tool
- Clearly flag when information is time-sensitive or may be outdated

Data classification: PUBLIC
You may discuss: market prices, news, analyst ratings, macro data, sector trends
You must NOT: access or infer specific user portfolio positions or personal financial data

When citing sources, always include: source name, publication date, and key quote.
""".strip()


class MarketIntelAgent(BaseAgent):
    """Market intelligence agent backed by a Foundry Prompt Agent with Bing Grounding."""

    name = "market_intel_agent"
    description = "Market news, analyst commentary and narratives, earnings coverage, sector trends — real-time Bing-grounded search (not structured data)"
    example_queries: list = [
        "What are the latest analyst upgrades or downgrades for NVDA?",
        "What are analysts saying about the semiconductor sector outlook?",
        "What happened in the market today?",
        "What is the latest news on Apple earnings?",
    ]
    system_message = MARKET_INTEL_INSTRUCTIONS

    @classmethod
    def create(cls, settings, credential, context_providers=None, **kwargs):
        """
        Override create() — this agent builds its own RawFoundryAgentChatClient
        rather than accepting a shared FoundryChatClient.

        Uses Agent + RawFoundryAgentChatClient so that:
        - The agent satisfies HandoffBuilder's isinstance(participant, Agent) check
        - The underlying client connects to the pre-configured Foundry Prompt Agent
          (portfolio-market-intel) which has Bing Grounding baked in server-side.

        Bing Grounding is a *hosted* tool on the Foundry Agents service — it must be
        defined on the server-side agent definition, not attached at call time.

        Args:
            settings: Application Settings (foundry_project_endpoint, market_intel_agent_name)
            credential: Shared AsyncTokenCredential (from the orchestrator)
            context_providers: Optional list (e.g. AzureAISearchContextProvider)
        """
        from agent_framework import Agent
        from agent_framework.foundry import RawFoundryAgentChatClient

        market_client = RawFoundryAgentChatClient(
            project_endpoint=settings.foundry_project_endpoint,
            agent_name=settings.market_intel_agent_name,
            credential=credential,
        )
        agent_kwargs = {
            "client": market_client,
            "name": cls.name,
            "instructions": cls.system_message,
            "require_per_service_call_history_persistence": True,
        }
        if context_providers:
            agent_kwargs["context_providers"] = context_providers
        return Agent(**agent_kwargs)

    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — build with the orchestrator's shared credential."""
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        return cls.create(
            ctx.settings,
            ctx.credential,
            context_providers=ctx.context_providers,
        )


def create_market_intel_agent(settings, credential, context_providers=None):
    """Backward-compat factory — prefer MarketIntelAgent.create() in new code."""
    return MarketIntelAgent.create(settings, credential, context_providers=context_providers)


async def get_market_intel_foundry_agent(settings: Settings):
    """
    Connect to the pre-configured Prompt Agent in Foundry (standalone use).

    Use this for standalone invocation outside the Handoff workflow.
    The agent is configured in Foundry portal with Bing Grounding enabled.

    Reference: https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/providers/foundry/foundry_agent_basic.py
    """
    from agent_framework.foundry import FoundryAgent

    credential = DefaultAzureCredential(
        managed_identity_client_id=settings.azure_client_id or None
    )
    return FoundryAgent(
        project_endpoint=settings.foundry_project_endpoint,
        agent_name=settings.market_intel_agent_name,
        credential=credential,
    )
