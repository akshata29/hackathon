# ============================================================
# Portfolio data API routes
# Returns per-user portfolio data seeded deterministically from the user's identity.
# The user identity is extracted from the validated Entra JWT (oid claim).
# In production: replace _build_user_portfolio() with real Fabric/SQL query.
# ============================================================

import logging
import random
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.core.auth.middleware import require_authenticated_user
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Deterministic per-user synthetic data
# Uses the user's OID (stable Entra object ID) as the random seed so each
# user always sees the same portfolio, but different from every other user.
# ---------------------------------------------------------------------------

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


def _build_user_portfolio(user_id: str) -> dict[str, Any]:
    rng = random.Random(hash(user_id) & 0xFFFFFFFF)
    # Pick 8-12 holdings for this user
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
            "current_price": price,
            "market_value": value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
            "weight_pct": 0.0,  # filled below
        })

    for h in holdings:
        h["weight_pct"] = round(h["market_value"] / total_value * 100, 2)

    holdings.sort(key=lambda h: h["market_value"], reverse=True)

    # Sector allocation
    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[h["sector"]] = round(sectors.get(h["sector"], 0) + h["weight_pct"], 1)

    # Performance metrics — deterministic but varied per user
    ytd = round(rng.uniform(-5.0, 28.0), 1)
    sharpe = round(rng.uniform(0.6, 2.1), 2)
    alpha = round(rng.uniform(-3.0, 6.0), 1)
    beta = round(rng.uniform(0.75, 1.35), 2)
    performance = {
        "total_value": round(total_value, 2),
        "ytd_return": ytd,
        "one_year_return": round(ytd * rng.uniform(1.2, 1.8), 1),
        "three_year_annualized": round(rng.uniform(6.0, 18.0), 1),
        "benchmark": "S&P 500",
        "benchmark_ytd": 12.1,
        "alpha": alpha,
        "beta": beta,
        "sharpe_ratio": sharpe,
        "max_drawdown": round(rng.uniform(-18.0, -3.0), 1),
        "volatility": round(rng.uniform(10.0, 22.0), 1),
    }

    return {
        "holdings": holdings,
        "sectors": [{"sector": k, "weight": v} for k, v in sectors.items()],
        "performance": performance,
    }


# ---------------------------------------------------------------------------
# Routes — all require authentication
# ---------------------------------------------------------------------------

@router.get("/holdings")
async def get_holdings(
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_id = user_claims.get("oid") or user_claims.get("sub", "dev")
    data = _build_user_portfolio(user_id)
    return {
        "holdings": data["holdings"],
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
        "currency": "USD",
    }


@router.get("/performance")
async def get_performance(
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_id = user_claims.get("oid") or user_claims.get("sub", "dev")
    data = _build_user_portfolio(user_id)
    return {
        "performance": data["performance"],
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
    }


@router.get("/sector-allocation")
async def get_sector_allocation(
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_id = user_claims.get("oid") or user_claims.get("sub", "dev")
    data = _build_user_portfolio(user_id)
    return {
        "allocations": data["sectors"],
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
    }
