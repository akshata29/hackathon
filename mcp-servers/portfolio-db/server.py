# ============================================================
# Portfolio DB MCP Server
# Exposes CONFIDENTIAL user portfolio data via MCP.
# Row-level security: every request MUST include X-User-Id header.
# The backend passes the authenticated user's preferred_username (email) as
# X-User-Id so each user only sees their own portfolio data.
#
# Data source priority:
#   1. SQLite database at DB_PATH (seeded by scripts/seed-portfolio-db.py)
#   2. Deterministic in-memory synthetic data (fallback / first-run)
#
# In production: replace _load_from_db() with Fabric/SQL query.
# ============================================================

from dotenv import load_dotenv
load_dotenv()

import logging
import os
import re
import sqlite3
import time

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
    get_user_id_from_request,
    make_prm_app,
    MCP_CLIENT_ID,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth provider
# ---------------------------------------------------------------------------
# Production (ENTRA_TENANT_ID set): EntraTokenVerifier validates the OBO JWT
# against Entra JWKS; audience = api://<MCP_CLIENT_ID>.
#
# Dev mode (ENTRA_TENANT_ID not set): falls back to static MCP_AUTH_TOKEN
# comparison inside EntraTokenVerifier.verify_token().
# ---------------------------------------------------------------------------
auth_provider = MultiIDPTokenVerifier()

mcp = FastMCP(
    name="portfolio-db-mcp",
    instructions=(
        "You have access to CONFIDENTIAL portfolio data for the authenticated user. "
        "This includes holdings, transactions, performance, and asset allocation. "
        "Data classification: CONFIDENTIAL. "
        "NEVER return data belonging to a user other than the one authenticated via the Bearer token. "
        "NEVER include PII in responses beyond what the user already provided."
    ),
    auth=auth_provider,
)


# Health check endpoint (no auth required)
@mcp.custom_route("/healthz", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "service": "portfolio-db-mcp"})

# Path to the seeded SQLite database.  Set DB_PATH to enable persistent RLS storage.
DB_PATH = os.getenv("DB_PATH", "")

# ---------------------------------------------------------------------------
# Input validation helpers
# ---------------------------------------------------------------------------

# Valid ticker symbols: 1-10 uppercase alphanumeric chars plus . - ^ = (BRK.B, ^GSPC, etc.)
_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-\^=]{1,10}$")


def _validate_symbol(symbol: str) -> str:
    """Normalise and validate a ticker symbol. Raises ValueError on bad input."""
    s = symbol.upper().strip()
    if not _SYMBOL_RE.match(s):
        raise ValueError(f"Invalid ticker symbol: {symbol!r}")
    return s


# ---------------------------------------------------------------------------
# SQLite data access (row-level security enforced by user_id parameter)
# ---------------------------------------------------------------------------

def _db_connect() -> sqlite3.Connection | None:
    if not DB_PATH:
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn
    except Exception as exc:
        logger.warning("Cannot connect to portfolio DB at %s: %s", DB_PATH, exc)
        return None


def _db_get_holdings(user_id: str) -> list[dict] | None:
    conn = _db_connect()
    if not conn:
        return None
    try:
        rows = conn.execute(
            "SELECT * FROM holdings WHERE user_id = ? ORDER BY market_value DESC",
            (user_id,),
        ).fetchall()
        if not rows:
            return None
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _db_get_portfolio_summary(user_id: str) -> dict | None:
    conn = _db_connect()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT total_value, cash, profile FROM portfolios WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _db_get_performance(user_id: str) -> dict | None:
    conn = _db_connect()
    if not conn:
        return None
    try:
        row = conn.execute(
            "SELECT * FROM performance WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _db_get_transactions(user_id: str, symbol: str | None = None, limit: int = 50) -> list[dict] | None:
    conn = _db_connect()
    if not conn:
        return None
    try:
        if symbol:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ? AND symbol = ? ORDER BY trade_date DESC LIMIT ?",
                (user_id, symbol.upper(), limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM transactions WHERE user_id = ? ORDER BY trade_date DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        if rows is None:
            return None
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# In-memory fallback (deterministic synthetic data)
# Uses hashlib.md5 instead of Python's hash() to avoid PYTHONHASHSEED
# non-determinism across processes.
# ---------------------------------------------------------------------------

import hashlib
import random as _random

_HOLDINGS_UNIVERSE = [
    ("AAPL", "Apple Inc.", "Technology", 185.0),
    ("MSFT", "Microsoft Corp.", "Technology", 415.0),
    ("NVDA", "NVIDIA Corp.", "Technology", 875.0),
    ("GOOGL", "Alphabet Inc.", "Technology", 165.0),
    ("META", "Meta Platforms", "Technology", 520.0),
    ("JPM", "JPMorgan Chase", "Financials", 198.0),
    ("GS", "Goldman Sachs", "Financials", 478.0),
    ("BRK.B", "Berkshire Hathaway B", "Financials", 368.0),
    ("BLK", "BlackRock Inc.", "Financials", 890.0),
    ("UNH", "UnitedHealth Group", "Healthcare", 490.0),
    ("JNJ", "Johnson & Johnson", "Healthcare", 152.0),
    ("LLY", "Eli Lilly", "Healthcare", 890.0),
    ("XOM", "ExxonMobil", "Energy", 108.0),
    ("CVX", "Chevron Corp.", "Energy", 155.0),
    ("AMZN", "Amazon.com Inc.", "Consumer Discretionary", 185.0),
    ("TSLA", "Tesla Inc.", "Consumer Discretionary", 250.0),
]


def _stable_seed(user_id: str) -> int:
    return int.from_bytes(hashlib.md5(user_id.encode()).digest()[:4], "big")


def _build_user_portfolio(user_id: str) -> dict:
    rng = _random.Random(_stable_seed(user_id))
    count = rng.randint(8, min(12, len(_HOLDINGS_UNIVERSE)))
    chosen = rng.sample(_HOLDINGS_UNIVERSE, count)

    holdings = []
    total_value = 0.0
    for sym, name, sector, base_price in chosen:
        price = round(base_price * rng.uniform(0.85, 1.15), 2)
        shares = rng.randint(20, 500)
        value = round(price * shares, 2)
        cost_basis = round(value * rng.uniform(0.65, 1.25), 2)
        pnl = round(value - cost_basis, 2)
        pnl_pct = round(pnl / max(cost_basis, 0.01) * 100, 2)
        total_value += value
        holdings.append({
            "symbol": sym,
            "name": name,
            "sector": sector,
            "shares": shares,
            "avg_cost": round(cost_basis / max(shares, 1), 2),
            "current_price": price,
            "market_value": value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "weight_pct": 0.0,
        })

    for h in holdings:
        h["weight_pct"] = round(h["market_value"] / total_value * 100, 2)

    holdings.sort(key=lambda h: h["market_value"], reverse=True)

    sector_map: dict[str, float] = {}
    for h in holdings:
        sector_map[h["sector"]] = round(sector_map.get(h["sector"], 0) + h["weight_pct"], 1)

    # Performance metrics — same RNG sequence as backend route
    ytd = round(rng.uniform(-5.0, 28.0), 1)
    sharpe = round(rng.uniform(0.6, 2.1), 2)
    alpha = round(rng.uniform(-3.0, 6.0), 1)
    beta = round(rng.uniform(0.75, 1.35), 2)
    one_year = round(ytd * rng.uniform(1.2, 1.8), 1)
    three_year = round(rng.uniform(6.0, 18.0), 1)
    max_drawdown = round(rng.uniform(-18.0, -3.0), 1)
    volatility = round(rng.uniform(10.0, 22.0), 1)
    cash = round(rng.uniform(5000, 50000), 2)

    return {
        "total_value": round(total_value, 2),
        "cash": cash,
        "holdings": holdings,
        "sector_allocation": [{"sector": k, "weight_pct": v} for k, v in sector_map.items()],
        "performance": {
            "total_value": round(total_value, 2),
            "ytd_return": ytd,
            "one_year_return": one_year,
            "three_year_annualized": three_year,
            "benchmark": "S&P 500",
            "benchmark_ytd": 12.1,
            "alpha": alpha,
            "beta": beta,
            "sharpe_ratio": sharpe,
            "max_drawdown": max_drawdown,
            "volatility": volatility,
        },
    }


_PORTFOLIOS: dict[str, dict] = {
    "dev": _build_user_portfolio("dev"),
    "user-001": _build_user_portfolio("user-001"),
}


def _get_user_id_from_context() -> str:
    """Return the authenticated user's identity for row-level security.

    Production: extracts oid from the OBO token (cryptographically verified by
    EntraTokenVerifier before this tool function was invoked).
    Dev mode: reads X-User-Id header for backward compatibility.
    """
    return get_user_id_from_request()


def _get_portfolio(user_id: str) -> dict:
    """Return portfolio dict; SQLite takes priority over in-memory fallback."""
    holdings_rows = _db_get_holdings(user_id)
    if holdings_rows is not None:
        summary = _db_get_portfolio_summary(user_id) or {}
        total_value = summary.get("total_value", sum(h["market_value"] for h in holdings_rows))
        # Recompute weights from DB values (in case DB has stale weight_pct)
        for h in holdings_rows:
            h["weight_pct"] = round(h["market_value"] / max(total_value, 0.01) * 100, 2)
        sector_map: dict[str, float] = {}
        for h in holdings_rows:
            sector_map[h["sector"]] = round(sector_map.get(h["sector"], 0) + h["weight_pct"], 2)
        return {
            "total_value": round(total_value, 2),
            "cash": summary.get("cash", 0.0),
            "holdings": holdings_rows,
            "sector_allocation": [{"sector": k, "weight_pct": v} for k, v in sector_map.items()],
            "_source": "sqlite",
        }
    # Fallback: deterministic in-memory data
    if user_id not in _PORTFOLIOS:
        _PORTFOLIOS[user_id] = _build_user_portfolio(user_id)
    return _PORTFOLIOS[user_id]


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_holdings() -> dict:
    """
    Get the current portfolio holdings for the authenticated user.

    Returns:
        dict with list of holdings (symbol, name, sector, shares, current_price,
        market_value, unrealized_pnl, unrealized_pnl_pct, weight_pct) and total_value
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        logger.info("get_holdings called for user: %s", user_id)
        portfolio = _get_portfolio(user_id)
        _outcome = "success"
        return {
            "user_id": user_id,
            "total_value": portfolio["total_value"],
            "cash": portfolio["cash"],
            "holdings": portfolio["holdings"],
        }
    except PermissionError as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_holdings", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_allocation() -> dict:
    """
    Get the asset allocation breakdown by sector for the authenticated user.

    Returns:
        dict with sector_allocation list (sector, weight_pct) and total_value
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        portfolio = _get_portfolio(user_id)
        _outcome = "success"
        return {
            "user_id": user_id,
            "sector_allocation": portfolio["sector_allocation"],
            "total_value": portfolio["total_value"],
        }
    except PermissionError as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_allocation", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_performance_summary() -> dict:
    """
    Get a performance summary for the authenticated user's portfolio.

    Returns:
        dict with ytd_return, one_year_return, benchmark comparison, Sharpe ratio,
        max_drawdown, and similar metrics
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        portfolio = _get_portfolio(user_id)

        # Try SQLite performance record first
        db_perf = _db_get_performance(user_id)
        if db_perf:
            db_perf.pop("user_id", None)
            _outcome = "success"
            return {"user_id": user_id, "total_value": portfolio["total_value"], **db_perf}

        # Fallback: use performance metrics already computed in _build_user_portfolio
        perf = portfolio.get("performance", {})
        _outcome = "success"
        return {
            "user_id": user_id,
            "total_value": portfolio["total_value"],
            "ytd_return_pct": perf.get("ytd_return", 0.0),
            "one_year_return_pct": perf.get("one_year_return", 0.0),
            "three_year_annualized_pct": perf.get("three_year_annualized", 0.0),
            "benchmark": perf.get("benchmark", "S&P 500"),
            "benchmark_ytd_pct": perf.get("benchmark_ytd", 12.1),
            "alpha": perf.get("alpha", 0.0),
            "beta": perf.get("beta", 1.0),
            "sharpe_ratio": perf.get("sharpe_ratio", 1.0),
            "max_drawdown_pct": perf.get("max_drawdown", 0.0),
            "volatility_pct": perf.get("volatility", 0.0),
        }
    except PermissionError as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_performance_summary", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_transactions(symbol: str = "", limit: int = 20) -> dict:
    """
    Get trade history for the authenticated user.

    Args:
        symbol: filter by ticker symbol (e.g. AAPL); leave blank for all
        limit:  maximum number of transactions to return (default 20, max 100)

    Returns:
        dict with transactions list, each entry has symbol, trade_date, trade_type,
        shares, price, total_amount
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        if symbol:
            check_injection_patterns(symbol)
            check_content_safety(symbol)
        limit = min(max(1, limit), 100)
        if symbol:
            symbol = _validate_symbol(symbol)
        rows = _db_get_transactions(user_id, symbol or None, limit)
        if rows is not None:
            _outcome = "success"
            return {"user_id": user_id, "count": len(rows), "transactions": rows}
        # Fallback synthetic transactions
        rng = _random.Random(_stable_seed(user_id + "txns"))
        portfolio = _get_portfolio(user_id)
        txns = []
        from datetime import date, timedelta
        for i, h in enumerate(portfolio["holdings"][:limit]):
            if symbol and h["symbol"] != symbol.upper():
                continue
            td = (date(2024, 1, 2) + timedelta(days=i * 12)).isoformat()
            txns.append({
                "symbol": h["symbol"],
                "trade_date": td,
                "trade_type": "BUY",
                "shares": h["shares"],
                "price": round(h["avg_cost"], 2),
                "total_amount": round(h["shares"] * h["avg_cost"], 2),
            })
        _outcome = "success"
        return {"user_id": user_id, "count": len(txns), "transactions": txns}
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_transactions", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_holding_detail(symbol: str) -> dict:
    """
    Get detailed information for a single holding in the user's portfolio.

    Args:
        symbol: Stock ticker symbol (e.g. AAPL)

    Returns:
        dict with full holding details or error if symbol not held
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        check_injection_patterns(symbol)
        check_content_safety(symbol)
        symbol = _validate_symbol(symbol)
        portfolio = _get_portfolio(user_id)
        for h in portfolio["holdings"]:
            if h["symbol"] == symbol:
                _outcome = "success"
                return {"user_id": user_id, **h}
        _outcome = "success"
        return {"user_id": user_id, "symbol": symbol, "error": f"Symbol {symbol} not found in portfolio"}
    except (PermissionError, ValueError) as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_holding_detail", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


@mcp.tool()
def get_rebalancing_suggestions(target_tech_weight: float = 30.0) -> dict:
    """
    Suggest rebalancing trades to reach a target sector weighting.

    Args:
        target_tech_weight: Target Technology sector weight as a percentage (default 30%)

    Returns:
        dict with current vs target allocations and suggested trades
    """
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        target_tech_weight = max(0.0, min(100.0, target_tech_weight))
        portfolio = _get_portfolio(user_id)
        current_tech = sum(
            h["weight_pct"] for h in portfolio["holdings"] if h["sector"] == "Technology"
        )
        delta = target_tech_weight - current_tech
        direction = "reduce" if delta < 0 else "increase"
        _outcome = "success"
        return {
            "user_id": user_id,
            "current_tech_weight_pct": round(current_tech, 2),
            "target_tech_weight_pct": target_tech_weight,
            "delta_pct": round(delta, 2),
            "suggestion": (
                f"{direction.capitalize()} Technology exposure by {abs(delta):.1f}% "
                f"to reach {target_tech_weight}% target."
            ),
            "disclaimer": (
                "This is a model simulation only. Consult a licensed financial advisor "
                "before making any investment decisions."
            ),
        }
    except PermissionError as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_rebalancing_suggestions", user_id, _outcome, (time.monotonic() - _t0) * 1000, _err)


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

    port = int(os.getenv("PORT", "8002"))

    # Configure Azure Monitor OpenTelemetry — Camp 4: Monitoring & Telemetry
    # Conditional on APPLICATIONINSIGHTS_CONNECTION_STRING; no-op in dev.
    # Enables unified telemetry (request tracing + custom_dimensions) in
    # Application Insights alongside the backend and yahoo-finance MCP server.
    _conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if _conn_str:
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
            configure_azure_monitor(
                connection_string=_conn_str,
                logger_name="portfolio-db-mcp",
            )
            logger.info("Azure Monitor OpenTelemetry configured (portfolio-db-mcp)")
        except Exception as _otel_exc:
            logger.warning("Azure Monitor setup failed (non-blocking): %s", _otel_exc)

    uvicorn.run(make_prm_app(mcp, scopes=["portfolio.read"]), host="0.0.0.0", port=port)
