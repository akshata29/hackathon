# ============================================================
# GitHub OAuth2 routes  (Pattern 2 — vendor OAuth per-user token)
#
# This module demonstrates Pattern 2: an external vendor (GitHub) that has its
# own OAuth identity system and cannot accept Entra OBO tokens.
#
# Flow:
#   GET /api/auth/github          -- initiates OAuth, redirects to GitHub
#   GET /api/auth/github/callback -- receives code, exchanges for token, stores
#   GET /api/auth/github/status   -- returns whether the current user is connected
#   DELETE /api/auth/github       -- disconnects (deletes stored token)
#
# Prerequisites (set via env vars or Key Vault):
#   GITHUB_OAUTH_CLIENT_ID     -- GitHub OAuth App client ID
#   GITHUB_OAUTH_CLIENT_SECRET -- GitHub OAuth App client secret
#   GITHUB_OAUTH_REDIRECT_URI  -- must match the callback URL registered in the OAuth App
#
# To create a GitHub OAuth App:
#   https://github.com/settings/developers → OAuth Apps → New OAuth App
#   Homepage URL: <your frontend URL>
#   Callback URL: <backend URL>/api/auth/github/callback
#
# Security:
#   - State parameter is HMAC-signed (HS256 JWT) with the client secret to prevent CSRF.
#   - The user's oid is embedded in the state so the callback knows who to store for.
#   - Token is never returned to the frontend; it lives only in Cosmos DB.
# ============================================================

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.core.auth.middleware import require_auth_context
from app.core.auth.vendor_oauth_store import GitHubTokenStore

logger = logging.getLogger(__name__)
router = APIRouter()

_GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
# Scopes: read public repos and basic user info (no private repo access needed for market intel)
_GITHUB_SCOPES = "public_repo read:user"


# ─────────────────────────────────────────────────────────────────────
# State parameter helpers (HMAC-signed to prevent CSRF)
# ─────────────────────────────────────────────────────────────────────

def _make_state(user_oid: str, secret: str) -> str:
    """Encode user_oid + timestamp in a self-contained HMAC-signed state token."""
    payload = json.dumps({"oid": user_oid, "ts": int(time.time())})
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Base64-free: encode as <payload_hex>.<sig>
    return f"{payload.encode().hex()}.{sig}"


def _verify_state(state: str, secret: str, max_age_seconds: int = 600) -> str:
    """Verify and decode; returns user_oid or raises HTTPException."""
    try:
        hex_payload, sig = state.split(".", 1)
        payload_bytes = bytes.fromhex(hex_payload)
        expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise HTTPException(status_code=400, detail="Invalid OAuth state (tampered)")
        data = json.loads(payload_bytes)
        if int(time.time()) - data["ts"] > max_age_seconds:
            raise HTTPException(status_code=400, detail="OAuth state expired")
        return data["oid"]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Malformed OAuth state") from exc


# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────

@router.get("/github")
async def github_oauth_initiate(
    settings: Settings = Depends(get_settings),
    auth=Depends(require_auth_context),
):
    """
    Redirect the authenticated user to GitHub's OAuth authorization page.
    The returned redirect contains a signed state token embedding the user's oid.
    """
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=501,
            detail="GitHub OAuth not configured. Set GITHUB_OAUTH_CLIENT_ID.",
        )

    state = _make_state(auth.user_id, settings.github_oauth_client_secret)
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "scope": _GITHUB_SCOPES,
        "state": state,
    }
    url = f"{_GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/github/callback")
async def github_oauth_callback(
    code: str,
    state: str,
    settings: Settings = Depends(get_settings),
):
    """
    GitHub redirects here after the user authorizes the app.
    Exchange the code for an access token and store it in Cosmos DB.
    """
    if not settings.github_oauth_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    # Verify CSRF state and recover user_oid
    user_oid = _verify_state(state, settings.github_oauth_client_secret)

    # Exchange code -> access_token with GitHub
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            _GITHUB_OAUTH_TOKEN_URL,
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": settings.github_oauth_redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        token_data = resp.json()

    if "error" in token_data:
        logger.error("GitHub token exchange error: %s", token_data)
        raise HTTPException(
            status_code=400,
            detail=f"GitHub token exchange failed: {token_data.get('error_description', token_data['error'])}",
        )

    access_token = token_data.get("access_token", "")
    scope = token_data.get("scope", "")

    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in GitHub response")

    # Store the token in Cosmos DB keyed by user oid
    store = GitHubTokenStore(settings)
    try:
        await store.initialize()
        await store.store_token(user_oid=user_oid, access_token=access_token, scope=scope)
    finally:
        await store.close()

    logger.info("GitHub OAuth token stored for user %s (scope: %s)", user_oid, scope)

    # Redirect back to the frontend with a success indicator
    frontend_url = settings.github_oauth_redirect_uri.rsplit("/api/", 1)[0]
    return RedirectResponse(
        url=f"{frontend_url}?github_connected=true",
        status_code=302,
    )


@router.get("/github/status")
async def github_connection_status(
    settings: Settings = Depends(get_settings),
    auth=Depends(require_auth_context),
):
    """Return whether the current user has connected their GitHub account."""
    store = GitHubTokenStore(settings)
    try:
        await store.initialize()
        connected = await store.is_connected(auth.user_id)
    finally:
        await store.close()
    return {"connected": connected, "vendor": "github"}


@router.delete("/github")
async def github_disconnect(
    settings: Settings = Depends(get_settings),
    auth=Depends(require_auth_context),
):
    """Disconnect GitHub — removes the stored OAuth token from Cosmos DB."""
    store = GitHubTokenStore(settings)
    try:
        await store.initialize()
        await store.delete_token(auth.user_id)
    finally:
        await store.close()
    return {"disconnected": True, "vendor": "github"}
