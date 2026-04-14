# ============================================================
# ESG Advisor Agent  (A2A / Agent-to-Agent pattern)
#
# This agent demonstrates the A2A protocol integration pattern:
# instead of running locally it wraps a remotely-hosted A2A server
# (a2a-agents/esg-advisor/) as a tool callable by a regular Agent.
#
# HandoffBuilder requires Agent instances (not A2AAgent) because it needs
# cloning, tool injection, and middleware capabilities.  The integration
# pattern used here is:
#   1. Expose a Python async tool `query_esg_advisor(query)` that calls the
#      remote A2A server via the a2a-sdk client (JSON-RPC over HTTP).
#   2. Wrap that tool in a regular Agent so HandoffBuilder can accept it.
#
# Architecture:
#   backend (HandoffBuilder)
#       └─> esg_advisor_agent  [Agent with A2A tool]
#               └─> a2a-agents/esg-advisor (LangChain ReAct + yfinance)
#
# Configuration:
#   ESG_ADVISOR_URL in .env  (e.g. http://localhost:8010)
#   Leave unset to skip silently — the registry build loop filters None returns.
#
# Reference:
#   A2A spec:   https://github.com/google-deepmind/a2a
#   a2a-sdk:    https://github.com/a2a-sdk/python
# ============================================================

import logging

from app.core.agents.base import AgentBuildContext, BaseAgent

logger = logging.getLogger(__name__)

ESG_ADVISOR_DESCRIPTION = (
    "ESG ratings, sustainability risk scores, carbon footprint, controversy levels, "
    "and sector ESG peer benchmarks for portfolio holdings (Sustainalytics via Yahoo Finance)"
)

_ESG_INSTRUCTIONS = (
    "You are an ESG advisor specialist. "
    "Use the query_esg_advisor tool to answer all questions about ESG ratings, "
    "sustainability scores, carbon footprint, environmental/social/governance metrics, "
    "MSCI ESG ratings, Sustainalytics scores, and responsible investing. "
    "Always delegate to the tool — do not attempt to answer from memory."
)


def _make_query_esg_tool(esg_url: str):
    """Return an async tool function that calls the remote A2A ESG server."""

    async def query_esg_advisor(query: str) -> str:
        """Query the ESG Advisor A2A agent for ESG ratings, sustainability scores,
        carbon footprint, controversy levels, and peer benchmarks.

        Args:
            query: The ESG question or analysis request.

        Returns:
            ESG analysis text from the remote agent.
        """
        from agent_framework_a2a import A2AAgent

        agent = A2AAgent(url=esg_url, name="esg_advisor_a2a")
        async with agent:
            response = await agent.run(query)
        return response.text or str(response)

    return query_esg_advisor


class ESGAdvisorAgent(BaseAgent):
    """A2A-backed ESG Advisor specialist agent.

    When ESG_ADVISOR_URL is configured, creates a regular Agent whose single
    tool delegates queries to the remote A2A ESG server.  This satisfies
    HandoffBuilder's requirement for Agent instances while keeping the A2A
    protocol for transport.

    When the URL is absent (e.g. local dev without the server running),
    returns None so the registry loop skips it gracefully.
    """

    name = "esg_advisor_agent"
    description = ESG_ADVISOR_DESCRIPTION
    example_queries: list = [
        "What is AAPL's ESG and governance risk score?",
        "Show sustainability ratings for MSFT and GOOGL",
        "What is the environmental risk score for oil companies in my portfolio?",
        "Compare ESG scores for AAPL, MSFT, TSLA",
    ]
    system_message = _ESG_INSTRUCTIONS

    @classmethod
    def create_from_context(cls, ctx: AgentBuildContext):
        """Registry hook — create an Agent that wraps the remote A2A ESG server.

        Returns None when ESG_ADVISOR_URL is not set so the orchestrator
        silently skips this agent.
        """
        esg_url = getattr(ctx.settings, "esg_advisor_url", "")
        if not esg_url:
            logger.debug(
                "ESGAdvisorAgent: ESG_ADVISOR_URL not configured — skipping. "
                "Set esg_advisor_url in .env to enable ESG analysis."
            )
            return None

        from agent_framework import Agent

        logger.info("ESGAdvisorAgent: wrapping A2A server at %s as Agent tool", esg_url)
        return Agent(
            client=ctx.client,
            name=cls.name,
            description=cls.description,
            instructions=_ESG_INSTRUCTIONS,
            tools=[_make_query_esg_tool(esg_url)],
            require_per_service_call_history_persistence=True,
        )
