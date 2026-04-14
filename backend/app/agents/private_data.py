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
    description = "Real-time quotes, company financials, valuation multiples (P/E, EV/EBITDA, P/S), analyst ratings, analyst price targets, recommendation breakdowns, stock comparison"
    example_queries: list = [
        "What is AAPL's current P/E ratio and EV/EBITDA vs sector median?",
        "Show MSFT analyst price targets and recommendation breakdown",
        "Get NVDA's latest revenue and earnings figures",
        "Compare P/E ratios for AAPL, MSFT, GOOGL",
        "What are the analyst ratings and consensus for TSLA?",
    ]
    system_message = PRIVATE_DATA_INSTRUCTIONS

    @classmethod
    def build_tools(
        cls,
        yahoo_mcp_url: str,
        mcp_auth_token: str | None = None,
        raw_token: str | None = None,
        settings=None,
        demo_mode: str = "entra",
        mock_oidc_token: str | None = None,
        **kwargs,
    ) -> list:
        """
        Build the Yahoo Finance MCP tool.

        Security (production): OBOAuth exchanges the user's token for an OBO token
        scoped to api://<yahoo_mcp_client_id>/market.read.  The Yahoo Finance MCP
        validates via JWKS and checks the scope before serving any tool call.

        Security (entra-agent mode — agent_blueprint_client_id set):
          Uses AgentIdentityAuth: the backend's Managed Identity authenticates
          via the agent identity blueprint (federated credential, no secret).
          Token audience = api://<yahoo_mcp_client_id>/market.read.
          Yahoo Finance MCP validates via AgentIdentityTokenVerifier.
          Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/agent-identity

        Security (dev mode): plain bearer with static MCP_AUTH_TOKEN.

        Security (demo modes):
          "multi-idp"  — presents a mock Okta JWT directly; MCP validates via
                         MultiIDPTokenVerifier (requires TRUSTED_ISSUERS=http://localhost:8888).
          "okta-proxy" — routes through the Okta proxy (settings.okta_proxy_url);
                         proxy validates the mock JWT and swaps in a service token.

        Note: Yahoo Finance serves public market data so there is no per-user RLS;
        the OBO token still enforces that only authorized backends can call the MCP
        and provides an audit trail of which user triggered the request.
        """
        import httpx
        from agent_framework import MCPStreamableHTTPTool
        from app.core.auth.obo import build_obo_http_client
        from app.core.auth.agent_identity import build_agent_identity_http_client

        # Determine effective MCP URL — proxy intercepts in okta-proxy mode
        if demo_mode == "okta-proxy" and settings:
            effective_url = getattr(settings, "okta_proxy_url", yahoo_mcp_url)
        else:
            effective_url = yahoo_mcp_url

        # Build the HTTP client — mock token in demo modes, OBO in production
        if demo_mode in ("multi-idp", "okta-proxy") and mock_oidc_token:
            http_client = httpx.AsyncClient(
                headers={"Authorization": f"Bearer {mock_oidc_token}"}
            )
        elif demo_mode == "entra-agent":
            # Agent identity mode: no user OBO needed — agent acts under its own authority.
            mcp_client_id = getattr(settings, "yahoo_mcp_client_id", "") if settings else ""
            audience = f"api://{mcp_client_id}" if mcp_client_id else ""
            http_client = build_agent_identity_http_client(
                settings=settings,
                audience=audience,
                fallback_bearer=mcp_auth_token or "",
            )
        else:
            mcp_client_id = getattr(settings, "yahoo_mcp_client_id", "") if settings else ""
            http_client = build_obo_http_client(
                settings=settings,
                raw_token=raw_token,
                mcp_client_id=mcp_client_id,
                scope_name="market.read",
                fallback_bearer=mcp_auth_token or "",
            )

        return [
            MCPStreamableHTTPTool(
                name="YahooFinanceData",
                url=f"{effective_url}/mcp",
                approval_mode="never_require",
                http_client=http_client,
            )
        ]


    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — extract Yahoo Finance MCP config from settings."""
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        mock_oidc_tokens = getattr(ctx, "mock_oidc_tokens", {})
        return cls.create(
            ctx.client,
            yahoo_mcp_url=ctx.settings.yahoo_mcp_url,
            mcp_auth_token=ctx.settings.mcp_auth_token,
            raw_token=ctx.raw_token,
            settings=ctx.settings,
            demo_mode=getattr(ctx, "demo_mode", "entra"),
            mock_oidc_token=mock_oidc_tokens.get("yahoo"),
        )


def create_private_data_agent(
    client,
    yahoo_mcp_url: str,
    mcp_auth_token: str | None = None,
    raw_token: str | None = None,
    settings=None,
):
    """Backward-compat factory — prefer PrivateDataAgent.create() in new code."""
    return PrivateDataAgent.create(
        client,
        yahoo_mcp_url=yahoo_mcp_url,
        mcp_auth_token=mcp_auth_token,
        raw_token=raw_token,
        settings=settings,
    )
