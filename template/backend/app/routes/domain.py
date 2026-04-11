# ============================================================
# Domain data routes — TEMPLATE STUB
#
# Expose domain-specific data endpoints that your frontend dashboard
# and other clients consume directly (without going through the agent chat).
#
# Examples from the Portfolio Advisor:
#   GET /api/portfolio/holdings          — user's current positions
#   GET /api/portfolio/sector-allocation — aggregated by sector
#   GET /api/portfolio/performance       — P&L, Sharpe, drawdown
#
# Coding prompt: See template/docs/coding-prompts/README.md > Step 6
# ============================================================

import logging

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
# Optional: protect routes with Entra auth
# from app.core.auth.middleware import require_authenticated_user

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# TODO: Add your domain data endpoints below.
#
# Pattern A — public endpoint (no auth):
#
#   @router.get("/summary")
#   async def get_summary(settings: Settings = Depends(get_settings)):
#       data = fetch_from_your_database(settings)
#       return {"data": data}
#
# Pattern B — authenticated endpoint (requires Entra token):
#
#   from app.core.auth.middleware import require_authenticated_user
#   from typing import Any
#
#   @router.get("/my-data")
#   async def get_my_data(
#       user: dict = Depends(require_authenticated_user),
#       settings: Settings = Depends(get_settings),
#   ):
#       user_id = user.get("oid") or user.get("sub")
#       data = fetch_for_user(user_id, settings)
#       return {"data": data}
# ---------------------------------------------------------------------------


@router.get("/health")
async def domain_health():
    """Simple liveness check for the domain data layer."""
    return {"status": "ok"}
