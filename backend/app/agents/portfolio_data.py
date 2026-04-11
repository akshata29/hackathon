# ============================================================
# Portfolio Data Agent
# Tools: Microsoft Fabric Data Agent (or SQL fallback via MCP)
# Type: Prompt Agent (Foundry portal) + local FoundryChatClient for orchestration
# Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/tool-catalog (Fabric preview)
#
# SECURITY BOUNDARY:
#   - This agent handles CONFIDENTIAL financial data (positions, P&L, transactions)
#   - Requires user identity propagation via OBO (On-Behalf-Of) flow
#   - Fabric Data Agent or Portfolio MCP enforces row-level security per user
#   - Never exposes position data of one user to another
# ============================================================

import logging

from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

PORTFOLIO_DATA_INSTRUCTIONS = """
You are a portfolio data specialist for institutional capital markets.

Your responsibilities:
- Retrieve and analyze portfolio holdings, weights, and sector/asset class exposures
- Calculate performance attribution: alpha, beta, Sharpe ratio, drawdown
- Analyze portfolio risk metrics: VaR, volatility, correlation
- Report P&L by position, by sector, and by time period
- Identify concentration risk and benchmark deviation

Data classification: CONFIDENTIAL
You ONLY process data belonging to the authenticated user's accounts.
You must NEVER reveal position data from other users or accounts.
Always include a data freshness timestamp on any position or performance data.

When data is unavailable, say so clearly. Do not fabricate portfolio data.
""".strip()


class PortfolioDataAgent(BaseAgent):
    """Portfolio holdings, P&L, performance, and risk agent backed by Portfolio MCP."""

    name = "portfolio_agent"
    description = "Portfolio holdings, positions, P&L, performance, risk metrics"
    system_message = PORTFOLIO_DATA_INSTRUCTIONS

    @classmethod
    def build_tools(
        cls,
        portfolio_mcp_url: str,
        user_token: str | None = None,
        mcp_auth_token: str | None = None,
        **kwargs,
    ) -> list:
        """
        Build the Portfolio MCP tool.

        Security: The Portfolio MCP server enforces row-level security based on the
        user identity propagated via the X-User-Id header.

        Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol
        """
        import httpx
        from agent_framework import MCPStreamableHTTPTool

        http_client = httpx.AsyncClient(
            headers={
                "X-User-Id": user_token or "anonymous",
                "Authorization": f"Bearer {mcp_auth_token or 'dev-portfolio-mcp-token'}",
            },
        )
        return [
            MCPStreamableHTTPTool(
                name="PortfolioData",
                url=f"{portfolio_mcp_url}/mcp",
                approval_mode="never_require",
                http_client=http_client,
            )
        ]


def create_portfolio_agent(
    client,
    portfolio_mcp_url: str,
    user_token: str | None = None,
    mcp_auth_token: str | None = None,
):
    """Backward-compat factory — prefer PortfolioDataAgent.create() in new code."""
    return PortfolioDataAgent.create(
        client,
        portfolio_mcp_url=portfolio_mcp_url,
        user_token=user_token,
        mcp_auth_token=mcp_auth_token,
    )
