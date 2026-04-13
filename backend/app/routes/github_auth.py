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

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

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
# PKCE helpers (RFC 7636 / S256 method)
# ─────────────────────────────────────────────────────────────────────

def _generate_pkce() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using the S256 method.

    code_verifier:  43-128 URL-safe base64 characters (no padding)
    code_challenge: base64url(SHA-256(code_verifier)) — no padding
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
    digest = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return code_verifier, code_challenge


# ─────────────────────────────────────────────────────────────────────
# State parameter helpers (HMAC-signed to prevent CSRF)
# ─────────────────────────────────────────────────────────────────────

def _make_state(user_oid: str, secret: str, code_verifier: str = "") -> str:
    """Encode user_oid + timestamp + PKCE code_verifier in a self-contained HMAC-signed state token."""
    payload = json.dumps({"oid": user_oid, "ts": int(time.time()), "cv": code_verifier})
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    # Base64-free: encode as <payload_hex>.<sig>
    return f"{payload.encode().hex()}.{sig}"


def _verify_state(state: str, secret: str, max_age_seconds: int = 600) -> tuple[str, str]:
    """Verify and decode; returns (user_oid, code_verifier) or raises HTTPException."""
    try:
        hex_payload, sig = state.split(".", 1)
        payload_bytes = bytes.fromhex(hex_payload)
        expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise HTTPException(status_code=400, detail="Invalid OAuth state (tampered)")
        data = json.loads(payload_bytes)
        if int(time.time()) - data["ts"] > max_age_seconds:
            raise HTTPException(status_code=400, detail="OAuth state expired")
        return data["oid"], data.get("cv", "")
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
    Return the GitHub OAuth authorization URL as JSON.
    The frontend navigates to this URL to start the OAuth flow.
    Returns JSON {"auth_url": "..."} so the frontend can read it reliably
    without fighting browser redirect-manual / CORS opaque-redirect issues.
    """
    if not settings.github_oauth_client_id:
        raise HTTPException(
            status_code=501,
            detail="GitHub OAuth not configured. Set GITHUB_OAUTH_CLIENT_ID.",
        )

    # Use the stable OID (not preferred_username) so the key matches what
    # the chat endpoint uses when looking up the token. Access tokens for
    # custom API audiences may omit preferred_username, causing a mismatch.
    user_oid = auth.claims.get("oid") or auth.user_id
    code_verifier, code_challenge = _generate_pkce()
    state = _make_state(user_oid, settings.github_oauth_client_secret, code_verifier)
    params = {
        "client_id": settings.github_oauth_client_id,
        "redirect_uri": settings.github_oauth_redirect_uri,
        "scope": _GITHUB_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{_GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"
    return JSONResponse({"auth_url": auth_url})


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

    # Verify CSRF state and recover user_oid + PKCE code_verifier
    user_oid, code_verifier = _verify_state(state, settings.github_oauth_client_secret)

    # Exchange code -> access_token with GitHub
    async with httpx.AsyncClient(timeout=15) as client:
        exchange_data: dict = {
            "client_id": settings.github_oauth_client_id,
            "client_secret": settings.github_oauth_client_secret,
            "code": code,
            "redirect_uri": settings.github_oauth_redirect_uri,
        }
        if code_verifier:
            exchange_data["code_verifier"] = code_verifier
        resp = await client.post(
            _GITHUB_OAUTH_TOKEN_URL,
            data=exchange_data,
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
    return RedirectResponse(
        url=f"{settings.frontend_url}?github_connected=true",
        status_code=302,
    )


@router.get("/github/status")
async def github_connection_status(
    settings: Settings = Depends(get_settings),
    auth=Depends(require_auth_context),
):
    """Return whether the current user has connected their GitHub account."""
    user_oid = auth.claims.get("oid") or auth.user_id
    logger.info("github_status: oid=%r user_id=%r", user_oid, auth.user_id)
    store = GitHubTokenStore(settings)
    try:
        await store.initialize()
        connected = await store.is_connected(user_oid)
    finally:
        await store.close()
    return {"connected": connected, "vendor": "github"}


@router.delete("/github")
async def github_disconnect(
    settings: Settings = Depends(get_settings),
    auth=Depends(require_auth_context),
):
    """Disconnect GitHub — removes the stored OAuth token from Cosmos DB."""
    user_oid = auth.claims.get("oid") or auth.user_id
    store = GitHubTokenStore(settings)
    try:
        await store.initialize()
        await store.delete_token(user_oid)
    finally:
        await store.close()
    return {"disconnected": True, "vendor": "github"}
