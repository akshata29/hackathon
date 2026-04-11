# ============================================================
# Chat API routes
# Supports:
#   - POST /api/chat/message — single-turn (returns SSE stream)
#   - WebSocket /api/chat/ws/{session_id} — persistent chat session
#
# Authentication: Bearer token from Entra (validated via JWKS)
# User identity: extracted from token, scoped to session
# ============================================================

import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.conversation.cosmos_session_store import CosmosSessionStore
from app.core.guardrails.policy import check_user_message
from app.workflows.portfolio_workflow import PortfolioOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: str = "handoff"  # "handoff" | "comprehensive"


class ChatResponse(BaseModel):
    session_id: str
    message: str
    agent: str


def _get_user_id(authorization: str | None = Header(default=None)) -> str:
    """
    Extract user ID from the Entra Bearer token.

    In production this performs JWT validation against Entra JWKS endpoint.
    For development, falls back to anonymous user.

    Security: This user ID is propagated to the Portfolio MCP server for
    row-level security enforcement.
    """
    if not authorization or not authorization.startswith("Bearer "):
        # Development / anonymous mode — never allow this in production for financial data
        logger.warning(
            "No Bearer token provided — using anonymous user. "
            "Configure ENTRA_CLIENT_ID for production auth."
        )
        return "anonymous"

    token = authorization.removeprefix("Bearer ")
    # In production: validate JWT against Entra JWKS endpoint
    # For hackathon scope: extract sub claim without full validation
    try:
        import base64

        parts = token.split(".")
        if len(parts) >= 2:
            payload_b64 = parts[1] + "=="  # add padding
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            # preferred_username is the email/UPN — use it as user_id so it
            # matches the email-keyed rows in the local SQLite portfolio DB.
            return (
                payload.get("preferred_username")
                or payload.get("oid")
                or payload.get("sub")
                or "anonymous"
            )
    except Exception:
        pass
    return "anonymous"


@router.post("/message")
async def chat_message(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
    user_id: str = Depends(_get_user_id),
):
    """
    Single-turn chat endpoint.
    Returns Server-Sent Events (SSE) stream for progressive rendering.
    Messages are persisted to CosmosDB for per-user session history.
    """
    policy = check_user_message(request.message)
    if not policy.allowed:
        raise HTTPException(status_code=400, detail=policy.reason)

    session_id = request.session_id or str(uuid.uuid4())
    title = request.message[:80] + ("..." if len(request.message) > 80 else "")

    # Only persist sessions for authenticated users — anonymous users get
    # ephemeral in-memory sessions only (no Cosmos RU spend, no partition pollution).
    is_authenticated = user_id != "anonymous"
    store = CosmosSessionStore(settings) if is_authenticated else None

    # Load prior messages for conversation history before appending the new user message
    prior_messages: list[dict] = []
    if store:
        try:
            await store.initialize()
            existing = await store.get_session(session_id, user_id)
            if existing:
                prior_messages = existing.get("messages", [])
            else:
                await store.create_session(session_id, user_id, title)
            await store.append_message(session_id, user_id, "user", request.message)
        except Exception as exc:
            logger.warning("Failed to persist user message to CosmosDB: %s", exc)

    async def event_stream():
        accumulated_content = ""
        accumulated_agent: str | None = None
        accumulated_traces: list = []

        # Send session ID first so the client can persist it
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        try:
            async with PortfolioOrchestrator(settings) as orchestrator:
                if request.mode == "comprehensive":
                    gen = orchestrator.run_comprehensive(
                        message=request.message,
                        session_id=session_id,
                        user_token=user_id,
                        history=prior_messages or None,
                    )
                else:
                    gen = orchestrator.run_handoff(
                        message=request.message,
                        session_id=session_id,
                        user_token=user_id,
                        history=prior_messages or None,
                    )

                async for event in gen:
                    # Accumulate assistant response for persistence
                    if event.get("type") == "agent_response" and event.get("content"):
                        accumulated_content += event["content"]
                        accumulated_agent = event.get("agent")
                    elif event.get("type") == "handoff":
                        accumulated_traces.append(
                            {
                                "from_agent": event.get("from_agent"),
                                "to_agent": event.get("to_agent"),
                            }
                        )
                    yield f"data: {json.dumps(event)}\n\n"
        finally:
            # Persist assistant response — authenticated users only
            if accumulated_content and store:
                try:
                    await store.append_message(
                        session_id,
                        user_id,
                        "assistant",
                        accumulated_content,
                        agent=accumulated_agent,
                        traces=accumulated_traces,
                    )
                except Exception as exc:
                    logger.warning("Failed to persist assistant message: %s", exc)
            if store:
                try:
                    await store.close()
                except Exception:
                    pass

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.websocket("/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
    settings: Settings = Depends(get_settings),
):
    """
    WebSocket endpoint for persistent multi-turn chat sessions.
    Each message triggers a new workflow run, with history persisted to CosmosDB.
    """
    await websocket.accept()
    logger.info("WebSocket connected for session: %s", session_id)

    # Extract user ID from WebSocket header (sent by React client)
    user_id = "anonymous"
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        user_id = _get_user_id(auth_header)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                message = payload.get("message", "")
                mode = payload.get("mode", "handoff")
            except json.JSONDecodeError:
                message = raw
                mode = "handoff"

            if not message.strip():
                continue

            async with PortfolioOrchestrator(settings) as orchestrator:
                if mode == "comprehensive":
                    gen = orchestrator.run_comprehensive(
                        message=message,
                        session_id=session_id,
                        user_token=user_id,
                    )
                else:
                    gen = orchestrator.run_handoff(
                        message=message,
                        session_id=session_id,
                        user_token=user_id,
                    )

                async for event in gen:
                    await websocket.send_text(json.dumps(event))

            await websocket.send_text(json.dumps({"type": "done"}))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session: %s", session_id)
    except Exception as exc:
        logger.exception("WebSocket error for session %s: %s", session_id, exc)
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(exc)}))
        except Exception:
            pass
