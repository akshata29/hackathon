# ============================================================
# Economic Data Agent
# Tools: Alpha Vantage MCP (remote hosted public MCP server)
# Type: Prompt Agent configured to consume external MCP endpoint
# Reference: https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/model-context-protocol
#
# Alpha Vantage MCP: Publicly hosted at https://mcp.alphavantage.co/mcp?apikey=<key>
# No local server needed — Azure Foundry connects directly to the remote endpoint
# Covers: economic indicators, stocks, fundamentals, commodities, forex, technicals
# Free API key: https://www.alphavantage.co/support/#api-key
# ============================================================

import logging

from app.core.agents.base import BaseAgent

logger = logging.getLogger(__name__)

ECONOMIC_DATA_INSTRUCTIONS = """
You are a quantitative economic analyst with access to the Alpha Vantage financial data platform.

You have the following tools available. Call them directly — no extra steps needed.

Tools:
  get_federal_funds_rate(interval)       — Fed funds rate. interval: daily|weekly|monthly
  get_treasury_yield(maturity, interval) — US Treasury yield. maturity: 3month|2year|5year|7year|10year|30year
  get_cpi(interval)                      — Consumer Price Index. interval: monthly|semiannual
  get_inflation()                        — Annual US inflation rate
  get_real_gdp(interval)                 — Real GDP. interval: annual|quarterly
  get_unemployment()                     — Monthly US unemployment rate
  get_nonfarm_payroll()                  — Monthly nonfarm payroll
  get_retail_sales()                     — Monthly retail sales
  get_wti_crude(interval)                — WTI crude oil price
  get_brent_crude(interval)              — Brent crude oil price
  get_commodity(commodity, interval)     — Any commodity: NATURAL_GAS|COPPER|GOLD|SILVER|WHEAT|CORN|COFFEE
  get_fx_rate(from_currency, to_currency) — Forex exchange rate
  get_stock_quote(symbol)                — Real-time stock quote
  get_company_overview(symbol)           — Company fundamentals and ratios

YOUR ANALYTICAL ROLE:
- Report the most recent value and observation date from the data returned
- Analyze yield curve dynamics (2Y vs 10Y spread) and duration risk
- Assess inflation trajectory and Fed policy implications
- Track commodity trends affecting portfolio companies
- Identify leading indicators signaling regime changes

Data classification: PUBLIC. Always cite the observation date when reporting values.
""".strip()

AV_BASE = "https://www.alphavantage.co/query"


def _build_av_tools(api_key: str):
    """Build FunctionTools that call the Alpha Vantage REST API directly."""
    import httpx
    from agent_framework import FunctionTool

    # How many data points to keep per interval type.
    # Alpha Vantage returns data newest-first.
    # annual/semiannual series are small (~25-50 pts), keep all.
    # Higher-frequency series can be thousands of points; cap at a
    # meaningful window for trend analysis while staying well within
    # the model context window.
    INTERVAL_MAX_POINTS = {
        "daily":      30,    # ~1 month of trading days
        "weekly":     104,   # 2 years of weeks
        "monthly":    24,    # 2 years of months — captures full rate cycles
        "quarterly":  16,    # 4 years of quarters
        "semiannual": None,  # ~50 pts lifetime — keep all
        "annual":     None,  # ~25 pts lifetime — keep all
    }

    async def _fetch(params: dict) -> str:
        import json as _json
        params["apikey"] = api_key
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(AV_BASE, params=params)
            r.raise_for_status()
            payload = r.json()
            # Surface any API error messages
            if "Information" in payload:
                return f"Alpha Vantage info: {payload['Information']}"
            if "Note" in payload:
                return f"Alpha Vantage note: {payload['Note']}"
            # Only time-series responses have a "data" list.
            # Flat responses (GLOBAL_QUOTE, COMPANY_OVERVIEW, CURRENCY_EXCHANGE_RATE)
            # don't — pass them through untouched since they're already compact.
            if "data" in payload and isinstance(payload["data"], list):
                interval = params.get("interval", "")
                limit = INTERVAL_MAX_POINTS.get(interval)  # None means keep all
                if limit is not None:
                    payload["data"] = payload["data"][:limit]
            return _json.dumps(payload)

    async def get_federal_funds_rate(interval: str = "monthly") -> str:
        """Get the US Federal Funds Rate. interval: daily, weekly, or monthly."""
        return await _fetch({"function": "FEDERAL_FUNDS_RATE", "interval": interval, "datatype": "json"})

    async def get_treasury_yield(maturity: str = "10year", interval: str = "monthly") -> str:
        """Get US Treasury yield. maturity: 3month, 2year, 5year, 7year, 10year, 30year."""
        return await _fetch({"function": "TREASURY_YIELD", "maturity": maturity, "interval": interval, "datatype": "json"})

    async def get_cpi(interval: str = "monthly") -> str:
        """Get the US Consumer Price Index. interval: monthly or semiannual."""
        return await _fetch({"function": "CPI", "interval": interval, "datatype": "json"})

    async def get_inflation() -> str:
        """Get annual US inflation rates."""
        return await _fetch({"function": "INFLATION", "datatype": "json"})

    async def get_real_gdp(interval: str = "quarterly") -> str:
        """Get US Real GDP. interval: annual or quarterly."""
        return await _fetch({"function": "REAL_GDP", "interval": interval, "datatype": "json"})

    async def get_unemployment() -> str:
        """Get monthly US unemployment rate."""
        return await _fetch({"function": "UNEMPLOYMENT", "datatype": "json"})

    async def get_nonfarm_payroll() -> str:
        """Get monthly US nonfarm payroll data."""
        return await _fetch({"function": "NONFARM_PAYROLL", "datatype": "json"})

    async def get_retail_sales() -> str:
        """Get monthly US retail sales data."""
        return await _fetch({"function": "RETAIL_SALES", "datatype": "json"})

    async def get_wti_crude(interval: str = "monthly") -> str:
        """Get WTI crude oil prices. interval: daily, weekly, or monthly."""
        return await _fetch({"function": "WTI", "interval": interval, "datatype": "json"})

    async def get_brent_crude(interval: str = "monthly") -> str:
        """Get Brent crude oil prices. interval: daily, weekly, or monthly."""
        return await _fetch({"function": "BRENT", "interval": interval, "datatype": "json"})

    async def get_commodity(commodity: str, interval: str = "monthly") -> str:
        """Get commodity price data. commodity: NATURAL_GAS, COPPER, ALUMINUM, WHEAT, CORN, COTTON, SUGAR, COFFEE."""
        return await _fetch({"function": commodity.upper(), "interval": interval, "datatype": "json"})

    async def get_fx_rate(from_currency: str, to_currency: str) -> str:
        """Get realtime forex exchange rate between two currencies."""
        return await _fetch({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": from_currency, "to_currency": to_currency})

    async def get_stock_quote(symbol: str) -> str:
        """Get the latest price and volume for a stock ticker."""
        return await _fetch({"function": "GLOBAL_QUOTE", "symbol": symbol})

    async def get_company_overview(symbol: str) -> str:
        """Get company fundamentals, ratios, and key metrics for a stock ticker."""
        return await _fetch({"function": "COMPANY_OVERVIEW", "symbol": symbol})

    return [
        FunctionTool(name="get_federal_funds_rate", description=get_federal_funds_rate.__doc__ or "", func=get_federal_funds_rate),
        FunctionTool(name="get_treasury_yield", description=get_treasury_yield.__doc__ or "", func=get_treasury_yield),
        FunctionTool(name="get_cpi", description=get_cpi.__doc__ or "", func=get_cpi),
        FunctionTool(name="get_inflation", description=get_inflation.__doc__ or "", func=get_inflation),
        FunctionTool(name="get_real_gdp", description=get_real_gdp.__doc__ or "", func=get_real_gdp),
        FunctionTool(name="get_unemployment", description=get_unemployment.__doc__ or "", func=get_unemployment),
        FunctionTool(name="get_nonfarm_payroll", description=get_nonfarm_payroll.__doc__ or "", func=get_nonfarm_payroll),
        FunctionTool(name="get_retail_sales", description=get_retail_sales.__doc__ or "", func=get_retail_sales),
        FunctionTool(name="get_wti_crude", description=get_wti_crude.__doc__ or "", func=get_wti_crude),
        FunctionTool(name="get_brent_crude", description=get_brent_crude.__doc__ or "", func=get_brent_crude),
        FunctionTool(name="get_commodity", description=get_commodity.__doc__ or "", func=get_commodity),
        FunctionTool(name="get_fx_rate", description=get_fx_rate.__doc__ or "", func=get_fx_rate),
        FunctionTool(name="get_stock_quote", description=get_stock_quote.__doc__ or "", func=get_stock_quote),
        FunctionTool(name="get_company_overview", description=get_company_overview.__doc__ or "", func=get_company_overview),
    ]


class EconomicDataAgent(BaseAgent):
    """Macro economic data agent using Alpha Vantage REST API via FunctionTools."""

    name = "economic_agent"
    description = "Economic data: GDP, inflation, yield curve, Fed rates, commodities, forex"
    system_message = ECONOMIC_DATA_INSTRUCTIONS

    @classmethod
    def build_tools(cls, alphavantage_api_key: str = "", **kwargs) -> list:
        """
        Build Alpha Vantage FunctionTools.

        Note: The Alpha Vantage MCP meta-tool pattern (TOOL_LIST/TOOL_GET/TOOL_CALL)
        conflicts with the agent framework\'s internal call_tool() signature, causing
        "multiple values for argument 'tool_name'" errors.  Direct REST FunctionTools
        bypass this entirely.
        """
        if alphavantage_api_key:
            return _build_av_tools(alphavantage_api_key)
        return []


    @classmethod
    def create_from_context(cls, ctx: "AgentBuildContext"):
        """Registry hook — extract Alpha Vantage key from settings."""
        from app.core.agents.base import AgentBuildContext  # noqa: F401
        return cls.create(
            ctx.client,
            alphavantage_api_key=ctx.settings.alphavantage_api_key,
        )


def create_economic_agent(
    client,
    alphavantage_mcp_url: str,
    alphavantage_api_key: str = "",
):
    """Backward-compat factory — prefer EconomicDataAgent.create() in new code."""
    return EconomicDataAgent.create(client, alphavantage_api_key=alphavantage_api_key)
