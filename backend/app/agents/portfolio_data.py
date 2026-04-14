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
    description = "Portfolio holdings, positions, P&L, performance, risk metrics, exposures"
    example_queries: list = [
        "Show my current holdings and sector breakdown",
        "What is my portfolio P&L this quarter?",
        "What are my top 5 positions by weight?",
        "Show my risk metrics and concentration exposures",
    ]
    system_message = PORTFOLIO_DATA_INSTRUCTIONS

    @classmethod
    def build_tools(
        cls,
        portfolio_mcp_url: str,
        user_token: str | None = None,
        mcp_auth_token: str | None = None,
        raw_token: str | None = None,
        settings=None,
        demo_mode: str = "entra",
        mock_oidc_token: str | None = None,
        **kwargs,
    ) -> list:
        """
        Build the Portfolio MCP tool.

        Security (production — ENTRA_TENANT_ID + entra_client_secret set):
          Uses OBOAuth: the user's Entra Bearer token is exchanged for an OBO
          token scoped to api://<portfolio_mcp_client_id>/portfolio.read.
          The MCP server validates this token via JWKS; the oid claim is used
          for row-level security — no X-User-Id header needed or trusted.

        Security (entra-agent mode — agent_blueprint_client_id set):
          Uses AgentIdentityAuth: the backend's Managed Identity authenticates
          via the agent identity blueprint (federated credential, no secret).
          Token audience = api://<portfolio_mcp_client_id>/portfolio.read.
          No client secret stored anywhere.  The agent identity's oid (not a
          human user's oid) is the caller; portfolio MCP uses a shared demo
          view in this mode (no per-user RLS since there is no user token).
          Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity

        Security (dev mode):
          Falls back to X-User-Id header + static MCP_AUTH_TOKEN bearer.
          Both are required so the portfolio MCP can do RLS locally.

        Security (demo modes):
          "multi-idp"  — presents a mock Okta JWT directly; MCP validates via
                         MultiIDPTokenVerifier (TRUSTED_ISSUERS=http://localhost:8888).
          "okta-proxy" — no dedicated proxy for portfolio; falls back to multi-idp
                         style (direct mock-JWT call) so the demo still runs.

        Reference:
          https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol
          https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow
        """
        import httpx
        from agent_framework import MCPStreamableHTTPTool
        from app.core.auth.obo import build_obo_http_client
        from app.core.auth.agent_identity import build_agent_identity_http_client

        mcp_client_id = getattr(settings, "portfolio_mcp_client_id", "") if settings else ""

        # Build HTTP client based on mode
        if demo_mode in ("multi-idp", "okta-proxy") and mock_oidc_token:
            # Demo mode: use mock Okta JWT directly.
            # X-User-Id still needed so the MCP server can do RLS via header fallback
            # (the mock token carries `sub` but not Entra `oid`).
            http_client = httpx.AsyncClient(headers={
                "Authorization": f"Bearer {mock_oidc_token}",
                "X-User-Id": user_token or "demo-user",
            })
        elif demo_mode == "entra-agent":
            # Agent identity mode: authenticate as the agent itself (no user OBO).
            # The downstream MCP validates the token and grants access based on
            # the agent identity's RBAC role assignments.
            audience = f"api://{mcp_client_id}" if mcp_client_id else ""
            http_client = build_agent_identity_http_client(
                settings=settings,
                audience=audience,
                fallback_bearer=mcp_auth_token or "dev-portfolio-mcp-token",
            )
        else:
            # Production / dev: OBO or static bearer
            # In dev mode, include X-User-Id so the MCP server can still do RLS
            # via the header-based fallback path.
            extra_headers: dict = {}
            if not (settings and settings.entra_tenant_id and mcp_client_id and raw_token):
                extra_headers["X-User-Id"] = user_token or "anonymous"

            http_client = build_obo_http_client(
                settings=settings,
                raw_token=raw_token,
                mcp_client_id=mcp_client_id,
                scope_name="portfolio.read",
                fallback_bearer=mcp_auth_token or "dev-portfolio-mcp-token",
                extra_headers=extra_headers,
            )

        return [
            MCPStreamableHTTPTool(
                name="PortfolioData",
                url=f"{portfolio_mcp_url}/mcp",
                approval_mode="never_require",
                http_client=http_client,
            )
        ]

    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — extract Portfolio MCP config and auth tokens from context."""
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        mock_oidc_tokens = getattr(ctx, "mock_oidc_tokens", {})
        return cls.create(
            ctx.client,
            portfolio_mcp_url=ctx.settings.portfolio_mcp_url,
            user_token=ctx.user_token,
            mcp_auth_token=ctx.settings.mcp_auth_token,
            raw_token=ctx.raw_token,
            settings=ctx.settings,
            demo_mode=getattr(ctx, "demo_mode", "entra"),
            mock_oidc_token=mock_oidc_tokens.get("portfolio"),
        )


def create_portfolio_agent(
    client,
    portfolio_mcp_url: str,
    user_token: str | None = None,
    mcp_auth_token: str | None = None,
    raw_token: str | None = None,
    settings=None,
):
    """Backward-compat factory — prefer PortfolioDataAgent.create() in new code."""
    return PortfolioDataAgent.create(
        client,
        portfolio_mcp_url=portfolio_mcp_url,
        user_token=user_token,
        mcp_auth_token=mcp_auth_token,
        raw_token=raw_token,
        settings=settings,
    )
