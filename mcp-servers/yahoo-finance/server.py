# ============================================================
# Yahoo Finance MCP Server
# Exposes financial market data tools via MCP (Model Context Protocol)
# Deployed as an internal Container App; accessed by the backend via
# MCPStreamableHTTPTool using the Container App service URL.
#
# Auth: Entra ID JWT validation (production) / static token (dev)
#       Token is OBO-issued by the backend; validated via JWKS here.
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import re
import time
from functools import lru_cache

import yfinance as yf
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from entra_auth import (
    EntraTokenVerifier,
    MultiIDPTokenVerifier,
    audit_log,
    check_content_safety,
    check_injection_patterns,
    check_scope,
    get_caller_id,
    make_prm_app,
    MCP_CLIENT_ID,
    scan_output_credentials,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth provider
# ---------------------------------------------------------------------------
# Production (ENTRA_TENANT_ID set): validates OBO JWT (audience=api://<MCP_CLIENT_ID>).
# Dev mode: falls back to static MCP_AUTH_TOKEN comparison.
# ---------------------------------------------------------------------------
auth_provider = MultiIDPTokenVerifier()

mcp = FastMCP(
    name="yahoo-finance-mcp",
    instructions=(
        "You have access to real-time and historical financial market data via Yahoo Finance. "
        "Use these tools to fetch stock quotes, fundamentals, analyst ratings, and recent news. "
        "Data classification: PUBLIC market data. "
        "Do NOT include any PII or personally identifiable information in tool arguments."
    ),
    auth=auth_provider,
)


# Health check endpoint (no auth required)
@mcp.custom_route("/healthz", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "yahoo-finance-mcp"})


# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-\^=]{1,10}$")
_VALID_METRICS = frozenset({
    "pe_ratio", "forward_pe", "peg_ratio", "price_to_book",
    "return_on_equity", "debt_to_equity", "profit_margins",
})


def _validate_symbol(symbol: str) -> str:
    """Normalise and validate a ticker symbol. Raises ValueError on bad input."""
    s = symbol.upper().strip()
    if not _SYMBOL_RE.match(s):
        raise ValueError(f"Invalid ticker symbol: {symbol!r}")
    return s


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_quote(symbol: str) -> dict:
    """
    Get current stock quote for a given ticker symbol.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL, MSFT, NVDA)

    Returns:
        dict with price, change, change_pct, volume, market_cap, pe_ratio, week_52_high, week_52_low
    """
    caller_id = get_caller_id()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("market.read")
        check_injection_patterns(symbol)
        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        _outcome = "success"
        return {
            "symbol": symbol,
            "price": round(float(info.last_price or 0), 2),
            "previous_close": round(float(info.previous_close or 0), 2),
            "change": round(float((info.last_price or 0) - (info.previous_close or 0)), 2),
            "change_pct": round(
                float(((info.last_price or 0) - (info.previous_close or 0)) / max(info.previous_close or 1, 0.01) * 100),
                2,
            ),
            "volume": int(info.last_volume or 0),
            "market_cap": int(info.market_cap or 0),
            "fifty_two_week_high": round(float(info.year_high or 0), 2),
            "fifty_two_week_low": round(float(info.year_low or 0), 2),
        }
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        logger.warning("get_quote failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}
    finally:
        audit_log("get_quote", caller_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_financials(symbol: str) -> dict:
    """
    Get key financial metrics and valuation ratios for a stock.

    Args:
        symbol: Stock ticker symbol

    Returns:
        dict with pe_ratio, forward_pe, peg_ratio, price_to_book, revenue_growth,
        earnings_growth, return_on_equity, debt_to_equity, free_cash_flow_yield
    """
    caller_id = get_caller_id()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("market.read")
        check_injection_patterns(symbol)
        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
        info = yf.Ticker(symbol).info
        _outcome = "success"
        return {
            "symbol": symbol,
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "peg_ratio": info.get("pegRatio"),
            "price_to_book": info.get("priceToBook"),
            "price_to_sales_ttm": info.get("priceToSalesTrailing12Months"),
            "revenue_growth_yoy": info.get("revenueGrowth"),
            "earnings_growth_yoy": info.get("earningsGrowth"),
            "return_on_equity": info.get("returnOnEquity"),
            "return_on_assets": info.get("returnOnAssets"),
            "debt_to_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "gross_margins": info.get("grossMargins"),
            "operating_margins": info.get("operatingMargins"),
            "profit_margins": info.get("profitMargins"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        logger.warning("get_financials failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}
    finally:
        audit_log("get_financials", caller_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_news(symbol: str, max_items: int = 5) -> list[dict]:
    """
    Get recent news headlines and summaries for a stock.

    Args:
        symbol: Stock ticker symbol
        max_items: Maximum number of news items to return (default 5, max 10)

    Returns:
        list of dicts with title, publisher, link, published_at
    """
    caller_id = get_caller_id()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("market.read")
        check_injection_patterns(symbol)
        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
        max_items = min(max(1, max_items), 10)
        ticker = yf.Ticker(symbol)
        news = ticker.news or []
        results = []
        for item in news[:max_items]:
            content = item.get("content", {})
            results.append({
                "title": content.get("title") or item.get("title", ""),
                "publisher": (content.get("provider") or {}).get("displayName") or item.get("publisher", ""),
                "link": (content.get("canonicalUrl") or {}).get("url") or item.get("link", ""),
                "published_at": content.get("pubDate") or item.get("providerPublishTime", ""),
                "summary": content.get("summary", ""),
            })
        _outcome = "success"
        import json as _json
        return _json.loads(scan_output_credentials(_json.dumps(results)))
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        logger.warning("get_news failed for %s: %s", symbol, exc)
        return [{"symbol": symbol, "error": str(exc)}]
    finally:
        audit_log("get_news", caller_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_analyst_ratings(symbol: str) -> dict:
    """
    Get analyst consensus ratings and price targets for a stock.

    Args:
        symbol: Stock ticker symbol

    Returns:
        dict with recommendation, number_of_analysts, mean_target_price, high_target, low_target
    """
    caller_id = get_caller_id()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("market.read")
        check_injection_patterns(symbol)
        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
        info = yf.Ticker(symbol).info
        _outcome = "success"
        return {
            "symbol": symbol,
            "recommendation": info.get("recommendationKey"),
            "recommendation_mean": info.get("recommendationMean"),
            "number_of_analyst_opinions": info.get("numberOfAnalystOpinions"),
            "target_mean_price": info.get("targetMeanPrice"),
            "target_high_price": info.get("targetHighPrice"),
            "target_low_price": info.get("targetLowPrice"),
            "target_median_price": info.get("targetMedianPrice"),
        }
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        logger.warning("get_analyst_ratings failed for %s: %s", symbol, exc)
        return {"symbol": symbol, "error": str(exc)}
    finally:
        audit_log("get_analyst_ratings", caller_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def compare_stocks(symbols: list[str], metric: str = "pe_ratio") -> list[dict]:
    """
    Compare multiple stocks on a specific financial metric.

    Args:
        symbols: List of stock ticker symbols (max 5)
        metric: Metric to compare — one of: pe_ratio, forward_pe, peg_ratio,
                price_to_book, return_on_equity, debt_to_equity, profit_margins

    Returns:
        Sorted list of dicts with symbol and metric value
    """
    caller_id = get_caller_id()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("market.read")
        for s in symbols[:5]:
            check_injection_patterns(s)
            check_content_safety(s)
        check_injection_patterns(metric)
        check_content_safety(metric)
        symbols = [_validate_symbol(s) for s in symbols[:5]]
        if metric not in _VALID_METRICS:
            raise ValueError(f"Invalid metric {metric!r}. Choose from: {sorted(_VALID_METRICS)}")
        metric_map = {
            "pe_ratio": "trailingPE",
            "forward_pe": "forwardPE",
            "peg_ratio": "pegRatio",
            "price_to_book": "priceToBook",
            "return_on_equity": "returnOnEquity",
            "debt_to_equity": "debtToEquity",
            "profit_margins": "profitMargins",
        }
        yf_key = metric_map.get(metric, "trailingPE")
        results = []
        for sym in symbols:
            try:
                val = yf.Ticker(sym).info.get(yf_key)
                results.append({"symbol": sym, metric: val})
            except Exception as exc:
                results.append({"symbol": sym, metric: None, "error": str(exc)})
        _outcome = "success"
        return sorted(results, key=lambda x: (x[metric] is None, x[metric]))
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("compare_stocks", caller_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


if __name__ == "__main__":
    import asyncio
    import sys
    import uvicorn

    # Suppress benign WinError 10054 (connection reset) from ProactorEventLoop
    # when the MCP client closes the TCP connection after receiving the response.
    if sys.platform == "win32":
        def _suppress_connection_reset(loop, context):
            exc = context.get("exception")
            if isinstance(exc, ConnectionResetError):
                return
            loop.default_exception_handler(context)
        asyncio.get_event_loop().set_exception_handler(_suppress_connection_reset)

    port = int(os.getenv("PORT", "8001"))

    # Configure Azure Monitor OpenTelemetry — Camp 4: Monitoring & Telemetry
    # Conditional on APPLICATIONINSIGHTS_CONNECTION_STRING; no-op in dev.
    # Enables unified telemetry (request tracing + custom_dimensions) in
    # Application Insights alongside the backend and portfolio-db MCP server.
    _conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if _conn_str:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            configure_azure_monitor(
                connection_string=_conn_str,
                logger_name="yahoo-finance-mcp",
            )
            logger.info("Azure Monitor OpenTelemetry configured (yahoo-finance-mcp)")
        except Exception as _otel_exc:
            logger.warning("Azure Monitor setup failed (non-blocking): %s", _otel_exc)

    uvicorn.run(make_prm_app(mcp, scopes=["market.read"]), host="0.0.0.0", port=port)
