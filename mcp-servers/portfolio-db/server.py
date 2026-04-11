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

import logging
import os
import sqlite3

from fastmcp import FastMCP
from fastmcp.server.auth import StaticTokenVerifier

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Auth — shared bearer token validated by FastMCP
# ---------------------------------------------------------------------------
_AUTH_TOKEN = os.getenv("MCP_AUTH_TOKEN", "dev-portfolio-mcp-token")
auth_provider = StaticTokenVerifier(tokens={_AUTH_TOKEN: {"sub": "backend-service", "client_id": "backend"}})

mcp = FastMCP(
    name="portfolio-db-mcp",
    instructions=(
        "You have access to CONFIDENTIAL portfolio data for the authenticated user. "
        "This includes holdings, transactions, performance, and asset allocation. "
        "Data classification: CONFIDENTIAL. "
        "NEVER return data belonging to a user other than the one specified in X-User-Id. "
        "NEVER include PII in responses beyond what the user already provided."
    ),
    auth=auth_provider,
)

# Path to the seeded SQLite database.  Set DB_PATH to enable persistent RLS storage.
DB_PATH = os.getenv("DB_PATH", "")


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
# ---------------------------------------------------------------------------

def _build_user_portfolio(user_id: str) -> dict:
    import random
    rng = random.Random(hash(user_id))

    sectors = ["Technology", "Financials", "Healthcare", "Energy", "Consumer Discretionary"]
    base_holdings = [
        ("AAPL", "Apple Inc.", "Technology"),
        ("MSFT", "Microsoft Corp.", "Technology"),
        ("NVDA", "NVIDIA Corp.", "Technology"),
        ("JPM", "JPMorgan Chase", "Financials"),
        ("GS", "Goldman Sachs", "Financials"),
        ("UNH", "UnitedHealth Group", "Healthcare"),
        ("JNJ", "Johnson & Johnson", "Healthcare"),
        ("XOM", "ExxonMobil", "Energy"),
        ("AMZN", "Amazon.com Inc.", "Consumer Discretionary"),
        ("TSLA", "Tesla Inc.", "Consumer Discretionary"),
    ]

    holdings = []
    total_value = 0.0
    for sym, name, sector in base_holdings:
        shares = rng.randint(10, 500)
        price = rng.uniform(50, 900)
        value = round(shares * price, 2)
        cost = round(value * rng.uniform(0.6, 1.2), 2)
        total_value += value
        holdings.append({
            "symbol": sym,
            "name": name,
            "sector": sector,
            "shares": shares,
            "avg_cost": round(cost / shares, 2),
            "current_price": round(price, 2),
            "market_value": value,
            "unrealized_pnl": round(value - cost, 2),
            "unrealized_pnl_pct": round((value - cost) / max(cost, 0.01) * 100, 2),
        })

    for h in holdings:
        h["weight_pct"] = round(h["market_value"] / total_value * 100, 2)

    # Sector allocation
    sector_map: dict[str, float] = {}
    for h in holdings:
        sector_map[h["sector"]] = sector_map.get(h["sector"], 0) + h["weight_pct"]

    return {
        "total_value": round(total_value, 2),
        "holdings": holdings,
        "sector_allocation": [{"sector": k, "weight_pct": round(v, 2)} for k, v in sector_map.items()],
        "cash": round(rng.uniform(5000, 50000), 2),
    }


_PORTFOLIOS: dict[str, dict] = {
    "dev": _build_user_portfolio("dev"),
    "user-001": _build_user_portfolio("user-001"),
}


def _get_user_id_from_context() -> str:
    """
    Extract user ID from MCP request context headers.
    FastMCP exposes request headers via context; falls back to 'dev'.
    """
    try:
        from fastmcp.server.context import get_http_request
        req = get_http_request()
        if req:
            user_id = req.headers.get("x-user-id", "").strip()
            if user_id:
                return user_id
    except Exception:
        pass
    return "dev"


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
    logger.info("get_holdings called for user: %s", user_id)
    portfolio = _get_portfolio(user_id)
    return {
        "user_id": user_id,
        "total_value": portfolio["total_value"],
        "cash": portfolio["cash"],
        "holdings": portfolio["holdings"],
    }


@mcp.tool()
def get_allocation() -> dict:
    """
    Get the asset allocation breakdown by sector for the authenticated user.

    Returns:
        dict with sector_allocation list (sector, weight_pct) and total_value
    """
    user_id = _get_user_id_from_context()
    portfolio = _get_portfolio(user_id)
    return {
        "user_id": user_id,
        "sector_allocation": portfolio["sector_allocation"],
        "total_value": portfolio["total_value"],
    }


@mcp.tool()
def get_performance_summary() -> dict:
    """
    Get a performance summary for the authenticated user's portfolio.

    Returns:
        dict with ytd_return, one_year_return, benchmark comparison, Sharpe ratio,
        max_drawdown, and similar metrics
    """
    import random
    user_id = _get_user_id_from_context()
    portfolio = _get_portfolio(user_id)

    # Try SQLite performance record first
    db_perf = _db_get_performance(user_id)
    if db_perf:
        db_perf.pop("user_id", None)
        return {"user_id": user_id, "total_value": portfolio["total_value"], **db_perf}

    # Fallback: deterministic synthetic metrics
    rng = random.Random(hash(user_id + "perf"))
    ytd = round(rng.uniform(-5, 35), 2)
    return {
        "user_id": user_id,
        "total_value": portfolio["total_value"],
        "ytd_return_pct": ytd,
        "one_year_return_pct": round(ytd + rng.uniform(-5, 10), 2),
        "three_year_annualized_pct": round(rng.uniform(8, 18), 2),
        "benchmark": "S&P 500",
        "benchmark_ytd_pct": 12.1,
        "alpha": round(ytd - 12.1, 2),
        "beta": round(rng.uniform(0.8, 1.3), 2),
        "sharpe_ratio": round(rng.uniform(0.8, 2.2), 2),
        "max_drawdown_pct": round(rng.uniform(-20, -3), 2),
        "volatility_pct": round(rng.uniform(10, 22), 2),
    }


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
    limit = min(max(1, limit), 100)
    rows = _db_get_transactions(user_id, symbol or None, limit)
    if rows is not None:
        return {"user_id": user_id, "count": len(rows), "transactions": rows}
    # Fallback synthetic transactions
    import random
    rng = random.Random(hash(user_id + "txns"))
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
    return {"user_id": user_id, "count": len(txns), "transactions": txns}


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
    symbol = symbol.upper().strip()
    portfolio = _get_portfolio(user_id)
    for h in portfolio["holdings"]:
        if h["symbol"] == symbol:
            return {"user_id": user_id, **h}
    return {"user_id": user_id, "symbol": symbol, "error": f"Symbol {symbol} not found in portfolio"}


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
    portfolio = _get_portfolio(user_id)
    current_tech = sum(
        h["weight_pct"] for h in portfolio["holdings"] if h["sector"] == "Technology"
    )
    delta = target_tech_weight - current_tech
    direction = "reduce" if delta < 0 else "increase"
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
    uvicorn.run(mcp.http_app(), host="0.0.0.0", port=port)
