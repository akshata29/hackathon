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


def create_market_intel_agent(settings, credential, context_providers=None):
    """
    Create the market intelligence agent for use in the Handoff workflow.

    Uses Agent + RawFoundryAgentChatClient so that:
    - The agent satisfies HandoffBuilder's isinstance(participant, Agent) check
    - The underlying client connects to the pre-configured Foundry Prompt Agent
      (portfolio-market-intel) which has Bing Grounding baked into its server-side
      definition (configured by scripts/setup-foundry.py).

    Bing Grounding is a *hosted* tool on the Foundry Agents service — it cannot be
    attached at call time via a FunctionTool. It must be defined on the server-side
    agent definition, which is exactly what setup-foundry.py does via BingGroundingTool
    in the PromptAgentDefinition.

    Args:
        settings: Application Settings (provides project endpoint, market_intel_agent_name)
        credential: Shared AsyncTokenCredential (DefaultAzureCredential from the workflow)
        context_providers: Optional list (e.g., AzureAISearchContextProvider for research docs)

    Returns:
        Agent configured for handoff workflow participation backed by the Foundry Prompt Agent
    """
    from agent_framework import Agent
    from agent_framework.foundry import RawFoundryAgentChatClient

    # RawFoundryAgentChatClient connects to the pre-existing Foundry Prompt Agent by name.
    # The Prompt Agent has Bing Grounding configured server-side — no tool needs to be
    # passed here at call time.
    market_client = RawFoundryAgentChatClient(
        project_endpoint=settings.foundry_project_endpoint,
        agent_name=settings.market_intel_agent_name,
        credential=credential,
    )

    kwargs = {
        "client": market_client,
        "name": "market_intel_agent",
        "instructions": MARKET_INTEL_INSTRUCTIONS,
        # required by HandoffBuilder — all handoff participants must set this
        "require_per_service_call_history_persistence": True,
    }
    if context_providers:
        kwargs["context_providers"] = context_providers

    return Agent(**kwargs)


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
