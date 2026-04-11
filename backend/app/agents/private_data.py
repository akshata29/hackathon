# ============================================================
# Private Data Agent
# Tools: Yahoo Finance MCP (private internal MCP server)
# Type: Hosted Agent concept — full custom code with private MCP tool
# Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/hosted-agents
#
# Yahoo Finance MCP provides:
# - Real-time and delayed quotes (equities, ETFs, indices, FX)
# - Company financials: income statement, balance sheet, cash flow
# - Key statistics: P/E, EV/EBITDA, debt ratios, growth rates
# - Ownership data: institutional holders, insider transactions
#
# Security:
#   - Yahoo Finance MCP is internal (not externally reachable)
#   - Authenticated via Managed Identity headers
#   - Rate-limited per user to prevent abuse
# ============================================================

import logging

from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

PRIVATE_DATA_INSTRUCTIONS = """
You are a quantitative analyst specializing in real-time market data and company fundamentals.

Your data sources (via Yahoo Finance):
- Real-time/delayed quotes: price, volume, bid/ask, market cap
- Company financials: revenue, EBITDA, net income, EPS (TTM and forward)
- Balance sheet: total assets, debt, cash, book value
- Valuation multiples: P/E, P/B, P/S, EV/EBITDA, PEG ratio
- Analyst estimates: revenue/EPS consensus, price targets, recommendation distribution
- Technical data: 52-week range, moving averages, RSI

Your role in portfolio advisory:
- Provide current fundamental data for individual securities
- Calculate valuation vs. historical ranges and peer multiples
- Identify unusual options activity or institutional flows
- Support position-level analysis with real-time data

Data classification: PUBLIC (market data) / RESTRICTED (user-specific screening)
Always include data timestamp. Flag if quote is delayed vs. real-time.
""".strip()


class PrivateDataAgent(BaseAgent):
    """Real-time market data and company fundamentals agent backed by Yahoo Finance MCP."""

    name = "private_data_agent"
    description = "Real-time quotes, company financials, valuation multiples, technical data"
    system_message = PRIVATE_DATA_INSTRUCTIONS

    @classmethod
    def build_tools(
        cls,
        yahoo_mcp_url: str,
        mcp_auth_token: str | None = None,
        **kwargs,
    ) -> list:
        """
        Build the Yahoo Finance MCP tool.

        The Yahoo Finance MCP is a private internal service — not publicly accessible.
        Authentication uses a machine-to-machine bearer token.

        Design rationale: private MCP = controlled data boundary.  The MCP server
        can add rate limiting, audit logging, and PII scrubbing before data reaches
        the agent.  This is the "secure MCP" pattern.
        """
        import httpx
        from agent_framework import MCPStreamableHTTPTool

        http_headers = {}
        if mcp_auth_token:
            http_headers["Authorization"] = f"Bearer {mcp_auth_token}"

        return [
            MCPStreamableHTTPTool(
                name="YahooFinanceData",
                url=f"{yahoo_mcp_url}/mcp",
                approval_mode="never_require",
                http_client=httpx.AsyncClient(headers=http_headers),
            )
        ]


def create_private_data_agent(
    client,
    yahoo_mcp_url: str,
    mcp_auth_token: str | None = None,
):
    """Backward-compat factory — prefer PrivateDataAgent.create() in new code."""
    return PrivateDataAgent.create(
        client,
        yahoo_mcp_url=yahoo_mcp_url,
        mcp_auth_token=mcp_auth_token,
    )
