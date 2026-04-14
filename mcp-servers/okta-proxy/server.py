# ============================================================
# Option C — Okta-to-Entra Token Exchange Proxy
#
# Sits between the Copilot Studio / Okta consumer and the MCP server.
# Performs the token swap so the downstream MCP server never sees a
# raw Okta token and the user is not prompted for a second Entra login.
#
# Flow (dev mode — ENTRA_TENANT_ID not set):
#   1. Client sends request with Okta-issued Bearer token
#   2. Proxy validates token signature against OKTA_ISSUER JWKS
#   3. Proxy maps okta `sub`/`email` -> user identity via USER_MAPPING
#   4. Proxy replaces Authorization header with the static MCP dev token
#   5. Proxy adds X-Forwarded-User: <mapped-email> header
#   6. Proxy forwards full request (body + SSE) to TARGET_MCP_URL
#
# Flow (production — ENTRA_TENANT_ID set):
#   Steps 1-3 same.
#   4. Proxy obtains an Entra client_credentials token for the MCP app reg
#      (audience = api://<MCP_CLIENT_ID>)
#   5. Proxy adds X-Forwarded-User: <mapped-email>
#   6. Proxy forwards to TARGET_MCP_URL with the Entra service token
#
# Why not real OBO?
#   Entra's OBO grant (jwt-bearer) only accepts Entra-issued assertions.
#   An Okta JWT is NOT accepted.  The best that can be done without Entra
#   federation is a service (client_credentials) token + trusted user header.
#   This is safe because the MCP server is on internal-only ingress (ACA
#   external=false) — only the proxy can add that header.
#
# Simulation note:
#   Start mock-oidc/server.py first, then set:
#     OKTA_ISSUER=http://localhost:8888
#     OKTA_AUDIENCE=api://mock-mcp-client   (or your real MCP_CLIENT_ID)
#     TARGET_MCP_URL=http://localhost:8001  (yahoo-finance) or :8002 (portfolio)
#     TARGET_MCP_TOKEN=dev-yahoo-mcp-token  (must match MCP_AUTH_TOKEN on target)
#
# Configuration (env vars / .env):
#   See .env.example for all options.
# ============================================================

import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

load_dotenv(override=True)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT: int = int(os.getenv("PROXY_PORT", "8003"))

# OIDC issuer URL of the Okta (or mock-OIDC) server.
OKTA_ISSUER: str = os.getenv("OKTA_ISSUER", "http://localhost:8889")
# Expected audience in the incoming Okta token.
OKTA_AUDIENCE: str = os.getenv("OKTA_AUDIENCE", "api://mock-mcp-client")
# JWKS TTL cache in seconds.
JWKS_TTL: float = float(os.getenv("JWKS_CACHE_TTL", "3600"))

# URL of the downstream MCP server this proxy forwards to.
TARGET_MCP_URL: str = os.getenv("TARGET_MCP_URL", "http://localhost:8001")

# ---------------------------------------------------------------------------
# Dev mode (ENTRA_TENANT_ID not set)
# ---------------------------------------------------------------------------
# Static token injected into forwarded request (must match MCP_AUTH_TOKEN on target).
TARGET_MCP_TOKEN: str = os.getenv("TARGET_MCP_TOKEN", "dev-yahoo-mcp-token")

# ---------------------------------------------------------------------------
# Production mode (ENTRA_TENANT_ID set)
# ---------------------------------------------------------------------------
ENTRA_TENANT_ID: str = os.getenv("ENTRA_TENANT_ID", "")
ENTRA_CLIENT_ID: str = os.getenv("ENTRA_CLIENT_ID", "")   # proxy's own app reg
ENTRA_CLIENT_SECRET: str = os.getenv("ENTRA_CLIENT_SECRET", "")
# App registration client ID of the target MCP server.
MCP_CLIENT_ID: str = os.getenv("MCP_CLIENT_ID", "")

# ---------------------------------------------------------------------------
# User mapping: Okta sub/email -> MCP user identity
# ---------------------------------------------------------------------------
# JSON object: { "okta_sub_or_email": "entra_email_or_upn", ... }
# If a user is not in the mapping their Okta email/sub is passed through unchanged.
# Example env value: {"alice@okta.example":"alice@company.onmicrosoft.com"}
_USER_MAPPING_RAW: str = os.getenv("USER_MAPPING", "{}")
try:
    USER_MAPPING: dict = json.loads(_USER_MAPPING_RAW)
except json.JSONDecodeError:
    logger.warning("USER_MAPPING is not valid JSON; ignoring.")
    USER_MAPPING = {}

# ---------------------------------------------------------------------------
# JWKS cache for Okta/mock-OIDC validation
# ---------------------------------------------------------------------------
_okta_jwks_cache: dict | None = None
_okta_jwks_fetched_at: float = 0.0
_okta_jwks_uri: str | None = None


async def _get_okta_jwks() -> dict:
    global _okta_jwks_cache, _okta_jwks_fetched_at, _okta_jwks_uri
    if _okta_jwks_cache and (time.monotonic() - _okta_jwks_fetched_at) < JWKS_TTL:
        return _okta_jwks_cache
    async with httpx.AsyncClient(timeout=10) as client:
        if not _okta_jwks_uri:
            discovery = f"{OKTA_ISSUER.rstrip('/')}/.well-known/openid-configuration"
            resp = await client.get(discovery)
            resp.raise_for_status()
            _okta_jwks_uri = resp.json()["jwks_uri"]
        resp = await client.get(_okta_jwks_uri)
        resp.raise_for_status()
        _okta_jwks_cache = resp.json()
        _okta_jwks_fetched_at = time.monotonic()
    return _okta_jwks_cache  # type: ignore[return-value]


async def _validate_okta_token(token: str) -> dict:
    """Validate the Okta/mock JWT signature and return claims.

    Raises ValueError with a human-readable message on any failure.
    """
    from jose import JWTError, jwt

    try:
        header = jwt.get_unverified_header(token)
    except JWTError as e:
        raise ValueError(f"Malformed token header: {e}") from e

    kid = header.get("kid")
    jwks = await _get_okta_jwks()

    rsa_key: dict = {}
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            rsa_key = {k: key[k] for k in ("kty", "kid", "use", "n", "e") if k in key}
            break

    if not rsa_key:
        # Possible key rotation — flush cache
        global _okta_jwks_cache
        _okta_jwks_cache = None
        raise ValueError(f"JWKS key id={kid!r} not found for issuer {OKTA_ISSUER!r}")

    try:
        claims: dict = jwt.decode(
            token,
            rsa_key,
            algorithms=["RS256"],
            audience=OKTA_AUDIENCE,
            issuer=OKTA_ISSUER,
        )
    except JWTError as e:
        raise ValueError(f"Token validation failed: {e}") from e

    return claims


def _map_user(claims: dict) -> str:
    """Return the MCP-side user identity for the given Okta token claims."""
    # Try sub first, then email, then preferred_username
    for field in ("sub", "email", "preferred_username"):
        value = claims.get(field, "")
        if value:
            return USER_MAPPING.get(value, value)
    return "unknown"


# ---------------------------------------------------------------------------
# Entra client_credentials token cache (production mode)
# ---------------------------------------------------------------------------
_entra_token: str | None = None
_entra_token_expires_at: float = 0.0


async def _get_entra_service_token() -> str:
    """Obtain an Entra client_credentials token for the MCP app registration.

    The token audience is api://<MCP_CLIENT_ID>.
    Result is cached until 60 seconds before expiry.
    """
    global _entra_token, _entra_token_expires_at
    if _entra_token and time.monotonic() < _entra_token_expires_at - 60:
        return _entra_token

    token_url = (
        f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/oauth2/v2.0/token"
    )
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": ENTRA_CLIENT_ID,
                "client_secret": ENTRA_CLIENT_SECRET,
                "scope": f"api://{MCP_CLIENT_ID}/.default",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _entra_token = data["access_token"]
    _entra_token_expires_at = time.monotonic() + data.get("expires_in", 3600)
    logger.info("Obtained Entra client_credentials token (expires in %ds)", data.get("expires_in", 3600))
    return _entra_token  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Okta-to-Entra Token Exchange Proxy (Option C)",
    description=(
        "Validates an Okta JWT, maps user identity, then forwards the request "
        "to the downstream MCP server with a valid Entra/dev token."
    ),
)


@app.get("/healthz")
async def health() -> JSONResponse:
    mode = "production" if ENTRA_TENANT_ID else "dev"
    return JSONResponse({
        "status": "ok",
        "mode": mode,
        "okta_issuer": OKTA_ISSUER,
        "target_mcp": TARGET_MCP_URL,
    })


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"])
async def proxy(request: Request, path: str):
    """Transparent proxy: validate Okta token, swap auth, forward to MCP server.

    - Supports regular HTTP responses and SSE streaming.
    - Strips hop-by-hop headers that should not be forwarded.
    """
    # ------------------------------------------------------------------
    # 1. Extract incoming Bearer token
    # ------------------------------------------------------------------
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            {"error": "missing_token", "detail": "Authorization: Bearer <token> required"},
            status_code=401,
        )
    incoming_token = auth_header[7:]

    # ------------------------------------------------------------------
    # 2. Validate Okta/mock-OIDC token
    # ------------------------------------------------------------------
    try:
        claims = await _validate_okta_token(incoming_token)
    except ValueError as exc:
        logger.warning("Okta token rejected: %s", exc)
        return JSONResponse(
            {"error": "invalid_token", "detail": str(exc)},
            status_code=401,
        )

    # ------------------------------------------------------------------
    # 3. Map Okta user → MCP user identity
    # ------------------------------------------------------------------
    mcp_user = _map_user(claims)
    logger.info("Proxying request for user=%r path=/%s", mcp_user, path)

    # ------------------------------------------------------------------
    # 4. Obtain downstream token
    # ------------------------------------------------------------------
    if ENTRA_TENANT_ID:
        try:
            downstream_token = await _get_entra_service_token()
        except Exception as exc:
            logger.error("Failed to obtain Entra service token: %s", exc)
            return JSONResponse(
                {"error": "upstream_auth_failed", "detail": "Could not obtain Entra token"},
                status_code=502,
            )
    else:
        # Dev mode: use the static MCP dev token
        downstream_token = TARGET_MCP_TOKEN

    # ------------------------------------------------------------------
    # 5. Build forwarded headers
    # ------------------------------------------------------------------
    _HOP_BY_HOP = {
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade",
    }
    forwarded_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "authorization"
    }
    forwarded_headers["authorization"] = f"Bearer {downstream_token}"
    forwarded_headers["x-forwarded-user"] = mcp_user
    forwarded_headers["x-original-issuer"] = OKTA_ISSUER

    target_url = f"{TARGET_MCP_URL.rstrip('/')}/{path}"

    # ------------------------------------------------------------------
    # 6. Forward request; stream the response back
    #    Use client.stream() so SSE responses are forwarded incrementally.
    # ------------------------------------------------------------------
    body = await request.body()

    # We need to keep the httpx client alive until the caller finishes
    # consuming the response, so we manage the lifecycle via an async generator.
    async def _iter_upstream():
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    method=request.method,
                    url=target_url,
                    headers=forwarded_headers,
                    content=body,
                    params=dict(request.query_params),
                ) as upstream_resp:
                    # Stash status + headers so the outer scope can read them
                    # before iteration begins (populated on __aenter__).
                    _iter_upstream.status_code = upstream_resp.status_code
                    _iter_upstream.headers = dict(upstream_resp.headers)
                    _iter_upstream.ready = True
                    async for chunk in upstream_resp.aiter_bytes():
                        yield chunk
        except httpx.ConnectError:
            _iter_upstream.connect_error = True
            return

    _iter_upstream.status_code = 502
    _iter_upstream.headers = {}
    _iter_upstream.ready = False
    _iter_upstream.connect_error = False

    # Prime the generator until the response headers are available.
    gen = _iter_upstream()
    first_chunk: bytes | None = None
    try:
        first_chunk = await gen.__anext__()
    except StopAsyncIteration:
        pass
    except Exception as exc:
        logger.error("Upstream error: %s", exc)
        return JSONResponse({"error": "upstream_error", "detail": str(exc)}, status_code=502)

    if _iter_upstream.connect_error:
        return JSONResponse(
            {"error": "mcp_unreachable", "detail": f"Cannot connect to {TARGET_MCP_URL}"},
            status_code=502,
        )

    # Propagate response headers (excluding hop-by-hop)
    response_headers = {
        k: v
        for k, v in _iter_upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    content_type = _iter_upstream.headers.get("content-type", "")

    async def _prepend_first(first: bytes | None, rest):
        if first is not None:
            yield first
        async for chunk in rest:
            yield chunk

    return StreamingResponse(
        content=_prepend_first(first_chunk, gen),
        status_code=_iter_upstream.status_code,
        headers=response_headers,
        media_type="text/event-stream" if "text/event-stream" in content_type else None,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
