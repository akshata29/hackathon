# ============================================================
# Mock OIDC Server — simulates an Okta-like identity provider
# for local development and demos.
#
# Provides:
#   GET  /.well-known/openid-configuration  — OIDC discovery metadata
#   GET  /keys                              — JWKS (RS256 public key)
#   POST /token                             — issue a signed JWT
#   GET  /token/for/{user_email}            — convenience: quick dev token
#
# Usage:
#   Every token is signed with the same RSA-2048 key generated at startup.
#   Tokens expire after TOKEN_LIFETIME_SECONDS (default 3600).
#
# Wiring with MCP servers (Option B):
#   Set on MCP server env:
#     TRUSTED_ISSUERS=http://localhost:8888
#     MCP_CLIENT_ID=<your-entra-mcp-app-registration-client-id>
#   The MultiIDPTokenVerifier will auto-discover JWKS from this server
#   and validate tokens in the same way it validates Entra/Okta tokens.
#
# Wiring with Option C proxy:
#   Set on okta-proxy env:
#     OKTA_ISSUER=http://localhost:8888
#     OKTA_AUDIENCE=api://<MCP_CLIENT_ID>
# ============================================================

import json
import logging
import os
import time
import uuid

from dotenv import load_dotenv
load_dotenv()

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PORT: int = int(os.getenv("MOCK_OIDC_PORT", "8888"))
BASE_URL: str = os.getenv("MOCK_OIDC_BASE_URL", f"http://localhost:{PORT}")
TOKEN_LIFETIME: int = int(os.getenv("TOKEN_LIFETIME_SECONDS", "3600"))
# Audience to embed in issued tokens.  Must match MCP_CLIENT_ID on the MCP server.
# Can be overridden per-request via the /token endpoint.
DEFAULT_AUDIENCE: str = os.getenv("TOKEN_AUDIENCE", "api://mock-mcp-client")

# ---------------------------------------------------------------------------
# RSA key pair — generated once at startup
# ---------------------------------------------------------------------------
logger.info("Generating RSA-2048 key pair for OIDC token signing ...")
_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PUBLIC_KEY = _PRIVATE_KEY.public_key()
_KID = str(uuid.uuid4())  # stable across the lifetime of this process

logger.info("JWKS key id (kid): %s", _KID)
logger.info("Mock OIDC issuer:   %s", BASE_URL)
logger.info("Default audience:   %s", DEFAULT_AUDIENCE)

# ---------------------------------------------------------------------------
# Pre-compute JWKS from the public key
# ---------------------------------------------------------------------------
import base64
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()

_pub_numbers = _PUBLIC_KEY.public_numbers()
_JWKS = {
    "keys": [
        {
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "kid": _KID,
            "n": _int_to_base64url(_pub_numbers.n),
            "e": _int_to_base64url(_pub_numbers.e),
        }
    ]
}

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="Mock OIDC Server", description="Simulates Okta for local demo/dev")


@app.get("/.well-known/openid-configuration")
async def openid_configuration() -> JSONResponse:
    """OIDC discovery document — auto-discovered by MultiIDPTokenVerifier."""
    return JSONResponse({
        "issuer": BASE_URL,
        "authorization_endpoint": f"{BASE_URL}/authorize",
        "token_endpoint": f"{BASE_URL}/token",
        "jwks_uri": f"{BASE_URL}/keys",
        "response_types_supported": ["code", "token", "id_token"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "profile", "email", "portfolio.read", "market.read"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post"],
        "claims_supported": ["sub", "email", "name", "iss", "aud", "exp", "iat", "jti"],
    })


@app.get("/keys")
async def jwks() -> JSONResponse:
    """JWKS endpoint — returns the public key used to verify tokens."""
    return JSONResponse(_JWKS)


@app.post("/token")
async def issue_token(
    sub: str = Form(...),
    email: str = Form(None),
    name: str = Form(None),
    audience: str = Form(None),
    scope: str = Form("openid profile email portfolio.read market.read"),
) -> JSONResponse:
    """Issue a signed JWT for the given subject.

    Form fields:
      sub      — user subject (e.g. okta|abc123 or user@company.com)
      email    — optional email claim (defaults to sub if sub looks like an email)
      name     — optional display name
      audience — token audience; defaults to TOKEN_AUDIENCE env var
      scope    — space-separated scopes (default: full set)

    Returns: { "access_token": "<jwt>", "token_type": "Bearer", "expires_in": 3600 }
    """
    token = _mint_token(sub=sub, email=email, name=name, audience=audience, scope=scope)
    return JSONResponse({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": TOKEN_LIFETIME,
        "scope": scope,
    })


@app.get("/token/for/{user_email:path}")
async def quick_token(
    user_email: str,
    audience: str = None,
    scope: str = "openid profile email portfolio.read market.read",
) -> JSONResponse:
    """Convenience endpoint: GET /token/for/alice@company.com

    Returns a token with sub=email=user_email.  Useful for curl demos.
    """
    token = _mint_token(
        sub=user_email,
        email=user_email,
        name=user_email.split("@")[0].replace(".", " ").title(),
        audience=audience,
        scope=scope,
    )
    return JSONResponse({
        "access_token": token,
        "token_type": "Bearer",
        "expires_in": TOKEN_LIFETIME,
        "scope": scope,
        "hint": f"Authorization: Bearer {token[:40]}...",
    })


@app.get("/healthz")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "issuer": BASE_URL, "kid": _KID})


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _mint_token(
    sub: str,
    email: str | None,
    name: str | None,
    audience: str | None,
    scope: str,
) -> str:
    """Sign and return a JWT."""
    from jose import jwt as jose_jwt

    aud = audience or DEFAULT_AUDIENCE
    now = int(time.time())

    # If sub looks like an email, default email to sub
    if email is None and "@" in sub:
        email = sub

    payload: dict = {
        "iss": BASE_URL,
        "sub": sub,
        "aud": aud,
        "iat": now,
        "exp": now + TOKEN_LIFETIME,
        "jti": str(uuid.uuid4()),
        "scp": scope,
    }
    if email:
        payload["email"] = email
        payload["preferred_username"] = email
    if name:
        payload["name"] = name

    private_pem = _PRIVATE_KEY.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )

    token = jose_jwt.encode(
        payload,
        private_pem,
        algorithm="RS256",
        headers={"kid": _KID},
    )
    return token


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
