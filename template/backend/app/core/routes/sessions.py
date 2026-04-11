# ============================================================
# Session management REST API — generic, works for any use-case
#
# CORE SERVICE — do not add domain-specific logic here.
#
#   GET    /api/sessions              — list sessions for the current user
#   GET    /api/sessions/{id}         — get full session (with messages)
#   DELETE /api/sessions/{id}         — delete a session
#
# Authentication: same Bearer token strategy as /api/chat/message
# ============================================================

import logging

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.core.conversation.cosmos_session_store import CosmosSessionStore

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_user_id(authorization: str | None = Header(default=None)) -> str:
    """
    Extract user ID from Entra Bearer token (mirrors chat route).
    Falls back to 'anonymous' in development when no token is present.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return "anonymous"

    token = authorization.removeprefix("Bearer ")
    try:
        import base64
        import json

        parts = token.split(".")
        if len(parts) >= 2:
            payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=="))
            return payload.get("oid") or payload.get("sub") or "anonymous"
    except Exception:
        pass
    return "anonymous"


@router.get("")
async def list_sessions(
    user_id: str = Depends(_get_user_id),
    settings: Settings = Depends(get_settings),
):
    """Return all session summaries for the authenticated user, newest first."""
    store = CosmosSessionStore(settings)
    try:
        await store.initialize()
        sessions = await store.list_sessions(user_id)
        return {"sessions": sessions}
    except Exception as exc:
        logger.error("Failed to list sessions for user %s: %s", user_id, exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve sessions") from exc
    finally:
        await store.close()


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    user_id: str = Depends(_get_user_id),
    settings: Settings = Depends(get_settings),
):
    """Return the full session document including all messages."""
    store = CosmosSessionStore(settings)
    try:
        await store.initialize()
        session = await store.get_session(session_id, user_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found")
        return session
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve session") from exc
    finally:
        await store.close()


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(_get_user_id),
    settings: Settings = Depends(get_settings),
):
    """Delete a session owned by the current user."""
    store = CosmosSessionStore(settings)
    try:
        await store.initialize()
        deleted = await store.delete_session(session_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to delete session %s: %s", session_id, exc)
        raise HTTPException(status_code=500, detail="Failed to delete session") from exc
    finally:
        await store.close()
