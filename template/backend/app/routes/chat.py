# ============================================================
# Chat API routes -- TEMPLATE VERSION
# Supports:
#   - POST /api/chat/message -- single-turn (returns SSE stream)
#   - WebSocket /api/chat/ws/{session_id} -- persistent chat session
#
# ONLY CHANGE: replace AppOrchestrator import below with your orchestrator.
# Everything else (SSE streaming, session persistence, auth extraction)
# is generic and should not need modification.
#
# Coding prompt: See template/docs/coding-prompts/README.md > Step 3
# ============================================================

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.core.auth.middleware import AuthContext, require_auth_context
from app.core.conversation.cosmos_session_store import CosmosSessionStore
from app.core.guardrails.policy import check_user_message

# TODO: replace with your orchestrator
from app.workflows.workflow import AppOrchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

_VALID_DEMO_MODES = {"entra", "multi-idp", "okta-proxy"}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: str = "handoff"  # "handoff" | "comprehensive"
    # demo_mode controls which auth path the backend uses to reach MCP servers:
    #   "entra"      -- default; Entra OBO token exchange (production flow)
    #   "multi-idp"  -- Option B; backend presents a mock Okta JWT directly to MCP
    #                   (MCP uses MultiIDPTokenVerifier to validate both Entra + extra IdPs)
    #   "okta-proxy" -- Option C; calls routed through an identity-proxy (token swap)
    demo_mode: str = "entra"

    def model_post_init(self, __context) -> None:
        if self.demo_mode not in _VALID_DEMO_MODES:
            self.demo_mode = "entra"


@router.post("/message")
async def chat_message(
    request: ChatRequest,
    settings: Settings = Depends(get_settings),
    auth: AuthContext = Depends(require_auth_context),
):
    """
    Single-turn chat endpoint -- SSE stream response.
    Messages are persisted to CosmosDB for authenticated users.
    """
    user_id = auth.user_id
    raw_token = auth.raw_token

    policy = check_user_message(request.message)
    if not policy.allowed:
        raise HTTPException(status_code=400, detail=policy.reason)

    session_id = request.session_id or str(uuid.uuid4())
    title = request.message[:80] + ("..." if len(request.message) > 80 else "")

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
                await store.create_session(session_id, user_id, title, demo_mode=request.demo_mode)
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
            async with AppOrchestrator(settings) as orchestrator:
                if request.mode == "comprehensive":
                    gen = orchestrator.run_comprehensive(
                        message=request.message,
                        session_id=session_id,
                        user_token=user_id,
                        raw_token=raw_token,
                        history=prior_messages or None,
                        demo_mode=request.demo_mode,
                    )
                else:
                    gen = orchestrator.run_handoff(
                        message=request.message,
                        session_id=session_id,
                        user_token=user_id,
                        raw_token=raw_token,
                        history=prior_messages or None,
                        demo_mode=request.demo_mode,
                    )

                async for event in gen:
                    if event.get("type") == "agent_response" and event.get("content"):
                        accumulated_content += event["content"]
                        accumulated_agent = event.get("agent")
                    elif event.get("type") == "handoff":
                        accumulated_traces.append({
                            "from_agent": event.get("from_agent"),
                            "to_agent": event.get("to_agent"),
                        })
                    yield f"data: {json.dumps(event)}\n\n"
        finally:
            if accumulated_content and store:
                try:
                    await store.append_message(
                        session_id, user_id, "assistant", accumulated_content,
                        agent=accumulated_agent, traces=accumulated_traces,
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
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws/{session_id}")
async def chat_websocket(
    websocket: WebSocket,
    session_id: str,
    settings: Settings = Depends(get_settings),
):
    """WebSocket for persistent multi-turn chat sessions."""
    await websocket.accept()
    user_id = "anonymous"
    raw_token = ""
    auth_header = websocket.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        from app.core.auth.middleware import _decode_claims_unsafe
        raw_token = auth_header.removeprefix("Bearer ")
        claims = _decode_claims_unsafe(raw_token)
        user_id = (
            claims.get("preferred_username")
            or claims.get("oid")
            or claims.get("sub")
            or "anonymous"
        )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                payload = json.loads(raw)
                message = payload.get("message", "")
                mode = payload.get("mode", "handoff")
            except json.JSONDecodeError:
                message, mode = raw, "handoff"

            if not message.strip():
                continue

            async with AppOrchestrator(settings) as orchestrator:
                if mode == "comprehensive":
                    gen = orchestrator.run_comprehensive(
                        message=message,
                        session_id=session_id,
                        user_token=user_id,
                        raw_token=raw_token,
                    )
                else:
                    gen = orchestrator.run_handoff(
                        message=message,
                        session_id=session_id,
                        user_token=user_id,
                        raw_token=raw_token,
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