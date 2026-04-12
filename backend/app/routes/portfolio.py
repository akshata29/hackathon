# ============================================================
# Portfolio data API routes
# All data comes from the Portfolio MCP server — the single source of truth.
# The same MCP server the chat agent uses, so dashboard and chat always agree.
# ============================================================

import json
import logging
from datetime import datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth.middleware import require_authenticated_user
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# MCP client helper
# Calls a single tool on the Portfolio MCP server using the same auth
# mechanism as PortfolioDataAgent (OBO in production, static bearer in dev).
# ---------------------------------------------------------------------------

async def _call_portfolio_mcp_tool(
    tool_name: str,
    arguments: dict,
    settings: Settings,
    user_oid: str,
    raw_token: str | None,
) -> Any:
    """
    Call a Portfolio MCP tool and return the parsed result dict.

    Auth (mirrors PortfolioDataAgent.build_tools):
      Production: OBO token exchange via build_obo_http_client
      Dev mode:   static bearer + X-User-Id header for row-level security
    """
    # Build request headers directly — avoids nested httpx context manager issues
    # that cause empty SSE bodies when streaming inside client.stream().
    req_headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    has_entra = bool(
        settings.entra_tenant_id
        and settings.portfolio_mcp_client_id
        and settings.entra_backend_client_id
        and getattr(settings, "entra_client_secret", "")
        and raw_token
    )

    if has_entra:
        # Production: get OBO token once, then use it directly
        from app.core.auth.obo import OBOAuth
        scope = f"api://{settings.portfolio_mcp_client_id}/portfolio.read"
        obo = OBOAuth(
            tenant_id=settings.entra_tenant_id,
            client_id=settings.entra_backend_client_id,
            client_secret=getattr(settings, "entra_client_secret", ""),
            user_assertion=raw_token,
            scope=scope,
            fallback_bearer=settings.mcp_auth_token,
        )
        token = await obo._acquire()
        req_headers["Authorization"] = f"Bearer {token}"
    else:
        # Dev mode: static bearer + X-User-Id for row-level security
        req_headers["Authorization"] = f"Bearer {settings.mcp_auth_token}"
        req_headers["X-User-Id"] = user_oid

    endpoint = f"{settings.portfolio_mcp_url}/mcp"

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1 — initialize; extract Mcp-Session-Id for the tools/call
        init_resp = await client.post(endpoint, headers=req_headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "portfolio-dashboard", "version": "1.0"},
            },
        })
        call_headers = dict(req_headers)
        session_id = init_resp.headers.get("mcp-session-id") or init_resp.headers.get("Mcp-Session-Id")
        if session_id:
            call_headers["Mcp-Session-Id"] = session_id

        # Step 2 — tools/call; regular (non-streaming) post fully buffers the SSE body
        tool_resp = await client.post(endpoint, headers=call_headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        })
        if tool_resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Portfolio MCP error {tool_resp.status_code}")
        raw_body = tool_resp.text.strip()

    logger.debug("Portfolio MCP %s raw response: %r", tool_name, raw_body[:200])

    # FastMCP returns SSE-framed body: "event: message\r\ndata: {...}\r\n\r\n"
    body = raw_body
    if "data:" in raw_body:
        for line in raw_body.splitlines():
            if line.strip().startswith("data:"):
                body = line.strip()[len("data:"):].strip()
                break

    if not body:
        logger.error("Empty body from Portfolio MCP for tool %s. Raw: %r", tool_name, raw_body[:200])
        raise HTTPException(status_code=502, detail="Empty response from Portfolio MCP")

    rpc = json.loads(body)
    if "error" in rpc:
        raise HTTPException(status_code=502, detail=f"MCP tool error: {rpc['error']}")

    # MCP tool result is in result.content[0].text as a JSON string
    content = rpc.get("result", {}).get("content", [])
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])

    return rpc.get("result", {})


# ---------------------------------------------------------------------------
# Routes — all require authentication; all delegate to the Portfolio MCP
# ---------------------------------------------------------------------------

@router.get("/holdings")
async def get_holdings(
    request: Request,
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_oid = user_claims.get("oid") or user_claims.get("sub", "dev")
    raw_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None

    data = await _call_portfolio_mcp_tool("get_holdings", {}, settings, user_oid, raw_token)
    return {
        "holdings": data.get("holdings", []),
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
        "currency": "USD",
    }


@router.get("/performance")
async def get_performance(
    request: Request,
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_oid = user_claims.get("oid") or user_claims.get("sub", "dev")
    raw_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None

    data = await _call_portfolio_mcp_tool("get_performance_summary", {}, settings, user_oid, raw_token)
    # Normalise MCP field names to the shape the frontend expects
    performance = {
        "total_value": data.get("total_value", 0),
        "ytd_return": data.get("ytd_return_pct", data.get("ytd_return", 0)),
        "one_year_return": data.get("one_year_return_pct", data.get("one_year_return", 0)),
        "three_year_annualized": data.get("three_year_annualized_pct", data.get("three_year_annualized", 0)),
        "sharpe_ratio": data.get("sharpe_ratio", 0),
        "alpha": data.get("alpha", 0),
        "beta": data.get("beta", 1),
        "max_drawdown": data.get("max_drawdown_pct", data.get("max_drawdown", 0)),
        "volatility": data.get("volatility_pct", data.get("volatility", 0)),
    }
    return {
        "performance": performance,
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
    }


@router.get("/sector-allocation")
async def get_sector_allocation(
    request: Request,
    user_claims: dict = Depends(require_authenticated_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    user_oid = user_claims.get("oid") or user_claims.get("sub", "dev")
    raw_token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip() or None

    data = await _call_portfolio_mcp_tool("get_allocation", {}, settings, user_oid, raw_token)
    # MCP returns [{sector, weight_pct}]; frontend expects [{sector, weight}]
    raw_alloc = data.get("sector_allocation", [])
    allocations = [
        {"sector": a["sector"], "weight": a.get("weight_pct", a.get("weight", 0))}
        for a in raw_alloc
    ]
    return {
        "allocations": allocations,
        "user": user_claims.get("preferred_username") or user_claims.get("name", ""),
        "as_of": datetime.utcnow().isoformat(),
    }
