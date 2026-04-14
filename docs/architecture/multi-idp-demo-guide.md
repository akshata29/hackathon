# Multi-IDP Demo Guide: End-to-End Technical Reference

This document covers the complete technical implementation of the **Multi-IDP** and
**Okta-Proxy** demo modes in the Portfolio Advisor: every code path, config variable,
auth flow, and the specific bugs that were fixed during development.

---

## Table of Contents

1. [Overview and Problem Statement](#1-overview-and-problem-statement)
2. [Demo Modes at a Glance](#2-demo-modes-at-a-glance)
3. [Component Map](#3-component-map)
4. [Mock OIDC Server](#4-mock-oidc-server)
5. [Multi-IDP Mode (Option B) — End-to-End Flow](#5-multi-idp-mode-option-b--end-to-end-flow)
   - [Frontend: Demo Mode Selector](#51-frontend-demo-mode-selector)
   - [Backend: demo_mode Routing](#52-backend-demo_mode-routing)
   - [Mock Token Pre-Fetch](#53-mock-token-pre-fetch)
   - [Agent MCP Client Construction](#54-agent-mcp-client-construction)
   - [MultiIDPTokenVerifier on MCP Server](#55-multiidptokenverifier-on-mcp-server)
   - [Scope Enforcement](#56-scope-enforcement)
6. [Okta-Proxy Mode (Option C) — End-to-End Flow](#6-okta-proxy-mode-option-c--end-to-end-flow)
   - [Proxy Routing in PrivateDataAgent](#61-proxy-routing-in-privatedataagent)
7. [Entra Auth in the Frontend (MSAL)](#7-entra-auth-in-the-frontend-msal)
   - [Token Acquisition for Backend API Calls](#71-token-acquisition-for-backend-api-calls)
   - [Graph Token vs App Token Handling in Middleware](#72-graph-token-vs-app-token-handling-in-middleware)
8. [Session Persistence and CosmosDB](#8-session-persistence-and-cosmosdb)
9. [Agent Framework: HandoffBuilder + require_per_service_call_history_persistence](#9-agent-framework-handoffbuilder--require_per_service_call_history_persistence)
10. [SSE Streaming: Frontend Reader Loop](#10-sse-streaming-frontend-reader-loop)
11. [Environment Variables Reference (Demo Modes)](#11-environment-variables-reference-demo-modes)
12. [Startup Order for Local Demo](#12-startup-order-for-local-demo)
13. [Troubleshooting Reference](#13-troubleshooting-reference)

---

## 1. Overview and Problem Statement

Standard Entra ID authentication works via the OBO (On-Behalf-Of) flow: the frontend
sends a Bearer token issued for `api://<backend-client-id>`, the backend validates it,
then exchanges it (via OBO) for tokens scoped to each MCP server's app registration.

The demo modes exist to show what happens when the IDP is **not** Entra — e.g. an Okta
user calling the same MCP servers without any Entra identity.  Two approaches are
implemented and runnable locally:

| Mode | What happens |
|---|---|
| `entra` (default) | Full Entra OBO flow. Token signed by Entra, validated by JWKS, exchanged for MCP-scoped OBO token. |
| `multi-idp` | Backend fetches a mock Okta JWT (signed by local mock OIDC server). The JWT is sent **directly** to the MCP server. The MCP server's `MultiIDPTokenVerifier` validates it against the mock OIDC issuer's JWKS. |
| `okta-proxy` | Same mock JWT is sent to the Okta proxy (port 8003) instead of the MCP server directly. The proxy validates the mock JWT and substitutes a service-level credential before forwarding to the real MCP server. |
| `entra-agent` | Backend acquires an **app-only** Entra token using its own identity (no user OBO). MCP servers validate via `AgentIdentityTokenVerifier` (OID-pinned, no `scp` check). **Locally:** `DefaultAzureCredential` resolves to `az login` (your user account) or the `finagents` stand-in SP — not a real Foundry agent identity. **On Azure Container Apps:** Managed Identity + federated credential chain produces a genuine Entra Agent ID token. See [Local Dev vs. Real Entra Agent ID](#local-dev-vs-real-entra-agent-id-what-you-actually-see-in-each-environment) in the auth doc. |

---

## 2. Demo Modes at a Glance

```
                        Entra mode (default)
                        ─────────────────────────────────────────
Browser ──Entra JWT──► Backend ──OBO exchange──► MCP Server
                                   JWKS ◄────────── Entra JWKS endpoint
                                   OBO token audience = api://<MCP_CLIENT_ID>

                        Multi-IDP mode
                        ─────────────────────────────────────────
Browser ──Entra JWT──► Backend ──mock-OIDC-JWT──► MCP Server
                          │                        MultiIDPTokenVerifier
                          └── POST mock-oidc/token ──► mock OIDC server (port 8889)
                                                        (simulates Okta)

                        Okta-Proxy mode
                        ─────────────────────────────────────────
Browser ──Entra JWT──► Backend ──mock-OIDC-JWT──► Okta Proxy (port 8003)
                          │                         validates mock JWT
                          │                         swaps in service token
                          │                         ─────────────────────►
                          │                                          MCP Server
                          └── POST mock-oidc/token ──► mock OIDC server (port 8889)
```

---

## 3. Component Map

| Component | Port | File | Start command |
|---|---|---|---|
| Frontend (React + MSAL) | 5173 | `frontend/src/` | `1_run_frontend.bat` |
| Backend (FastAPI) | 8000 | `backend/app/` | `0_run_backend.bat` |
| Portfolio MCP (FastMCP) | 8002 | `mcp-servers/portfolio-db/server.py` | `2_run_mcp_portfolio.bat` |
| Yahoo Finance MCP (FastMCP) | 8001 | `mcp-servers/yahoo-finance/server.py` | `3_run_mcp_yahoo.bat` |
| Mock OIDC server | 8889 | `mcp-servers/mock-oidc/server.py` | `6_run_mock_oidc.bat` |
| Okta proxy | 8003 | `mcp-servers/okta-proxy/server.py` | `7_run_okta_proxy.bat` |
| ESG A2A agent | 8010 | `a2a-agents/esg-advisor/server.py` | `5_run_a2a_esg.bat` |
| Aspire dashboard | 18888 | Docker | `4_run_aspire_dashboard.bat` |

---

## 4. Mock OIDC Server

**File:** `mcp-servers/mock-oidc/server.py`
**Start:** `6_run_mock_oidc.bat` (port 8889)

The mock OIDC server simulates an Okta Authorization Server.  It issues RS256-signed JWTs
and publishes a standard OIDC discovery document.

### Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/.well-known/openid-configuration` | GET | OIDC discovery document (issuer, jwks_uri, token_endpoint) |
| `/keys` | GET | JWKS — public key used to sign tokens |
| `/token` | POST | Issue a token from form fields |
| `/token/for/<email>` | GET | Shortcut — issue demo token for an email address |

### Token issuance — POST /token

Form fields:
```
sub       = <subject identifier, usually email>
email     = <email claim>
audience  = api://<MCP_CLIENT_ID>   ← must match exactly what the MCP expects
scope     = openid profile email portfolio.read market.read
```

Response:
```json
{
  "access_token": "<RS256 JWT>",
  "token_type": "bearer",
  "expires_in": 3600
}
```

The issued JWT contains:
```json
{
  "iss": "http://localhost:8889",
  "sub": "<email>",
  "email": "<email>",
  "aud": "api://<MCP_CLIENT_ID>",
  "scp": "openid profile email portfolio.read market.read",
  "iat": <now>,
  "exp": <now + 3600>,
  "jti": "<uuid>"
}
```

**Key points:**
- The `aud` claim must match `api://{MCP_CLIENT_ID}` exactly — this is what
  `MultiIDPTokenVerifier` checks.
- The `scp` claim carries the scopes that `check_scope()` validates on the MCP servers.
- The private signing key is generated fresh at server startup and its public key is
  exposed at `/keys`.  Every restart invalidates all previously issued tokens.
- The issuer is `http://localhost:8889` — this value is added to `TRUSTED_ISSUERS` on
  each MCP server to activate multi-IDP validation.

### .env configuration

```ini
# mcp-servers/mock-oidc/.env
PORT=8889
TOKEN_EXPIRY_SECONDS=3600
```

---

## 5. Multi-IDP Mode (Option B) — End-to-End Flow

### 5.1 Frontend: Demo Mode Selector

**File:** `frontend/src/components/NavBar.tsx` (auth mode toggle)
**File:** `frontend/src/components/ChatPanel.tsx` (sends demo_mode in request body)
**File:** `frontend/src/App.tsx` (DemoMode state)

The UI presents three mode buttons: **Entra**, **Multi-IDP**, **Okta Proxy**.

Selecting **Multi-IDP** sets `demoMode = "multi-idp"` in React state.  Every subsequent
chat message includes `"demo_mode": "multi-idp"` in the POST body:

```typescript
// frontend/src/components/ChatPanel.tsx — handleSend()
body: JSON.stringify({
  message: userText,
  session_id: sessionId,
  mode: 'handoff',
  demo_mode: demoMode,   // "entra" | "multi-idp" | "okta-proxy"
})
```

The frontend sends a **real Entra Bearer token** for all modes (MSAL is always active
and always signed in with Entra).  The `demo_mode` field only changes how the **backend**
reaches the MCP servers — the Entra auth between browser and backend is unchanged.

### 5.2 Backend: demo_mode Routing

**File:** `backend/app/routes/chat.py` — `ChatRequest` model

```python
class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    mode: str = "handoff"
    demo_mode: str = "entra"   # validated against _VALID_DEMO_MODES

    def model_post_init(self, __context) -> None:
        if self.demo_mode not in _VALID_DEMO_MODES:
            self.demo_mode = "entra"  # safe fallback — never trust client input blindly
```

`_VALID_DEMO_MODES = {"entra", "multi-idp", "okta-proxy"}` — any unknown value is
silently downgraded to `"entra"` (fail-closed security behaviour).

The route forwards `demo_mode` to the orchestrator:

```python
# backend/app/routes/chat.py
gen = orchestrator.run_handoff(
    message=request.message,
    session_id=session_id,
    user_token=user_id,
    raw_token=raw_token,
    history=prior_messages or None,
    demo_mode=request.demo_mode,   # ← forwarded
)
```

### 5.3 Mock Token Pre-Fetch

**File:** `backend/app/workflows/portfolio_workflow.py`

`PortfolioOrchestrator.run_handoff()` overrides the base class method to pre-fetch mock
OIDC tokens **before** `build_specialist_agents()` is called.

```python
async def run_handoff(self, message, session_id, user_token=None,
                      raw_token=None, history=None, demo_mode="entra"):
    # 1. Pre-fetch GitHub token (Pattern 2 — async/sync boundary resolution)
    oid = self._extract_oid(raw_token, user_token)
    self._github_token = await self._fetch_github_token(oid)

    # 2. Pre-fetch mock OIDC tokens for non-Entra modes
    self._demo_mode = demo_mode
    self._mock_oidc_tokens: dict = {}
    if demo_mode in ("multi-idp", "okta-proxy"):
        user_email = (
            user_token
            if user_token and "@" in user_token
            else "demo@hackathon.local"
        )
        self._mock_oidc_tokens = await self._fetch_mock_oidc_tokens(user_email)

    async for event in super().run_handoff(...):
        yield event
```

`_fetch_mock_oidc_tokens()` issues two POST requests to the mock OIDC server — one
token per MCP audience:

```python
async def _fetch_mock_oidc_tokens(self, user_email: str) -> dict:
    base_url = self._settings.mock_oidc_url   # default: http://localhost:8889
    audiences = {
        "yahoo":     f"api://{self._settings.yahoo_mcp_client_id}",
        "portfolio": f"api://{self._settings.portfolio_mcp_client_id}",
    }
    # POST /token with { sub, email, audience, scope }
    # Returns { "yahoo": "<jwt>", "portfolio": "<jwt>" }
```

The two tokens have different `aud` claims — one scoped to the Yahoo Finance MCP
app registration, the other to the Portfolio MCP app registration.  This mirrors
how a real Okta-issued token would be scoped per-resource.

**Why pre-fetch?** `build_specialist_agents()` is a **synchronous** method (the Agent
Framework requires it).  Cosmos DB lookups and HTTP calls are `async`.  Pre-fetching
in the `async` `run_handoff()` wrapper allows the async work to complete before
the sync build phase reads the results via `getattr(self, "_mock_oidc_tokens", {})`.

### 5.4 Agent MCP Client Construction

**Files:**
- `backend/app/agents/portfolio_data.py` (`PortfolioDataAgent.build_tools`)
- `backend/app/agents/private_data.py` (`PrivateDataAgent.build_tools`)

Both agents check `demo_mode` before deciding how to authenticate to their MCP server:

```python
# backend/app/agents/portfolio_data.py
if demo_mode in ("multi-idp", "okta-proxy") and mock_oidc_token:
    # Direct mock-JWT path — present mock Okta token as-is
    # X-User-Id header provides fallback identity for RLS
    # (the mock token has `sub` but not Entra `oid`)
    http_client = httpx.AsyncClient(headers={
        "Authorization": f"Bearer {mock_oidc_token}",
        "X-User-Id": user_token or "demo-user",
    })
else:
    # Production / dev: OBO exchange or static bearer
    http_client = build_obo_http_client(
        settings=settings,
        raw_token=raw_token,
        mcp_client_id=mcp_client_id,
        scope_name="portfolio.read",
        fallback_bearer=mcp_auth_token,
    )
```

```python
# backend/app/agents/private_data.py
# Okta-proxy routes to a different URL; multi-idp uses same Yahoo MCP directly
if demo_mode == "okta-proxy" and settings:
    effective_url = getattr(settings, "okta_proxy_url", yahoo_mcp_url)
else:
    effective_url = yahoo_mcp_url

if demo_mode in ("multi-idp", "okta-proxy") and mock_oidc_token:
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {mock_oidc_token}"}
    )
else:
    http_client = build_obo_http_client(...)
```

The `mock_oidc_token` is passed from `AgentBuildContext.mock_oidc_tokens` (a dict
keyed `"yahoo"` / `"portfolio"`) which was set during the pre-fetch stage:

```python
# backend/app/workflows/portfolio_workflow.py — build_specialist_agents()
ctx = AgentBuildContext(
    client=self._client,
    ...
    demo_mode=getattr(self, "_demo_mode", "entra"),
    mock_oidc_tokens=getattr(self, "_mock_oidc_tokens", {}),
)

# backend/app/agents/private_data.py — create_from_context()
mock_oidc_tokens = getattr(ctx, "mock_oidc_tokens", {})
return cls.create(
    ctx.client,
    ...
    demo_mode=getattr(ctx, "demo_mode", "entra"),
    mock_oidc_token=mock_oidc_tokens.get("yahoo"),
)
```

### 5.5 MultiIDPTokenVerifier on MCP Server

**File:** `mcp-servers/yahoo-finance/entra_auth.py` (identical code in portfolio-db)

```python
class MultiIDPTokenVerifier(EntraTokenVerifier):
    """Validates tokens from Entra OR any trusted OIDC issuer."""

    def __init__(self) -> None:
        super().__init__()
        self._extra_issuers = [
            i.strip() for i in TRUSTED_ISSUERS_RAW.split(",") if i.strip()
        ] if TRUSTED_ISSUERS_RAW else []

    async def verify_token(self, token: str) -> AccessToken | None:
        # Fast path: no extra issuers — delegate entirely to Entra
        if not self._extra_issuers:
            return await super().verify_token(token)

        # Peek at issuer without signature verification
        unverified_claims = jwt.get_unverified_claims(token)
        iss: str = unverified_claims.get("iss", "")

        entra_issuer = f"https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0"
        entra_v1_issuer = f"https://sts.windows.net/{ENTRA_TENANT_ID}/"
        all_trusted = [entra_issuer, entra_v1_issuer] + self._extra_issuers

        if iss not in all_trusted:
            logger.warning("Rejected token: issuer %r not in trusted list", iss)
            return None

        if iss in (entra_issuer, entra_v1_issuer):
            return await super().verify_token(token)   # standard Entra path

        # Non-Entra issuer: discover and verify against that issuer's JWKS
        jwks = await _get_jwks_for_issuer(iss)
        # ... RS256 verify with audience=f"api://{MCP_CLIENT_ID}", issuer=iss
        claims = jwt.decode(token, rsa_key, algorithms=["RS256"],
                            audience=f"api://{MCP_CLIENT_ID}", issuer=iss)
        _request_claims.set(claims)
        return AccessToken(token=token, ...)
```

**JWKS discovery per issuer:**

```python
async def _get_jwks_for_issuer(issuer: str) -> dict:
    """Discover JWKS via <issuer>/.well-known/openid-configuration"""
    oidc_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
    resp = await client.get(oidc_url)
    jwks_uri = resp.json()["jwks_uri"]
    resp = await client.get(jwks_uri)
    jwks = resp.json()
    # Cached in _issuer_jwks_cache[issuer] with TTL = JWKS_CACHE_TTL (default 3600s)
    return jwks
```

For the mock OIDC server: `issuer = "http://localhost:8889"` →
discovers `http://localhost:8889/.well-known/openid-configuration` →
finds `jwks_uri = "http://localhost:8889/keys"` →
fetches the RSA public key generated at mock server startup.

**Activation (env var on MCP server):**

```ini
# mcp-servers/yahoo-finance/.env
TRUSTED_ISSUERS=http://localhost:8889
MCP_CLIENT_ID=<yahoo-mcp-app-registration-client-id>

# mcp-servers/portfolio-db/.env
TRUSTED_ISSUERS=http://localhost:8889
MCP_CLIENT_ID=<portfolio-mcp-app-registration-client-id>
```

With `ENTRA_TENANT_ID` also set, both Entra tokens (from OBO) and mock Okta tokens
(from the mock OIDC server) are accepted.  In development (no `ENTRA_TENANT_ID`),
the server falls back to static token comparison — multi-idp path is inactive.

### 5.6 Scope Enforcement

**File:** `mcp-servers/yahoo-finance/entra_auth.py` — `check_scope()`

```python
def check_scope(required_scope: str) -> None:
    if not ENTRA_TENANT_ID:
        return  # dev mode: skip scope enforcement

    claims = get_claims_from_request()
    scopes = claims.get("scp", "").split()       # delegated token (OBO/mock)
    roles: list = claims.get("roles", [])         # app token (client_credentials)
    # "mcp.call" app role grants access to all tools (okta-proxy service token)
    if required_scope not in scopes and required_scope not in roles and "mcp.call" not in roles:
        raise PermissionError(f"Missing required scope: {required_scope}")
```

In multi-idp mode: the mock Okta token's `scp` claim contains `market.read` (or
`portfolio.read`), so `check_scope("market.read")` passes.

In okta-proxy mode: the service token issued by the proxy carries the `mcp.call` app
role, so any scope check passes without needing the specific scope claim.

---

## 6. Okta-Proxy Mode (Option C) — End-to-End Flow

**File:** `mcp-servers/okta-proxy/server.py`
**Start:** `7_run_okta_proxy.bat` (port 8003)

The proxy is a lightweight ASGI application that:
1. Validates the incoming mock Okta JWT (`iss = http://localhost:8889` via JWKS).
2. Extracts the `sub` or `email` claim → user identity.
3. Applies `USER_MAPPING` dict if configured (Okta email → Entra UPN).
4. Acquires a service-level credential for the downstream MCP server:
   - Dev mode: uses `TARGET_MCP_TOKEN` (static string).
   - Prod mode: uses `client_credentials` grant → Entra service token.
5. Forwards the full request to `TARGET_MCP_URL` with the new Bearer token.
6. Injects `X-Forwarded-User: <mapped email>` for RLS on the MCP server.
7. Streams the response back (including SSE chunked encoding).

### 6.1 Proxy Routing in PrivateDataAgent

**File:** `backend/app/agents/private_data.py`

In `okta-proxy` mode, the agent changes the MCP endpoint URL but still provides the
mock Okta token as the Bearer:

```python
if demo_mode == "okta-proxy" and settings:
    effective_url = getattr(settings, "okta_proxy_url", yahoo_mcp_url)
    # → "http://localhost:8003"  (the proxy)
else:
    effective_url = yahoo_mcp_url
    # → "http://localhost:8001"  (Yahoo Finance MCP directly)

if demo_mode in ("multi-idp", "okta-proxy") and mock_oidc_token:
    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {mock_oidc_token}"}
    )
```

Traffic flow in okta-proxy mode:

```
Backend agent
    │  Bearer: <mock Okta JWT>   (audience = api://<yahoo-mcp-client-id>)
    ▼
Okta Proxy (port 8003)
    │  validate mock JWT via mock OIDC JWKS (localhost:8889/keys)
    │  extract email = "admin@MngEnvMCAP152362.onmicrosoft.com"
    │  apply USER_MAPPING (if set)
    │  acquire service token (dev: TARGET_MCP_TOKEN static string)
    │  add X-Forwarded-User: <email>
    ▼
Yahoo Finance MCP (port 8001)
    │  validates dev token (static match: TOKEN == _STATIC_DEV_TOKEN)
    │  reads X-Forwarded-User for audit log
    │  check_scope() skipped in dev mode (ENTRA_TENANT_ID not set)
    ▼
    Yahoo Finance API response → proxy → backend → SSE → browser
```

**Proxy configuration (`mcp-servers/okta-proxy/.env`):**

```ini
OKTA_ISSUER=http://localhost:8889
OKTA_AUDIENCE=api://<yahoo-mcp-client-id>    # must match mock token aud claim
TARGET_MCP_URL=http://localhost:8001          # downstream Yahoo Finance MCP
TARGET_MCP_TOKEN=dev-yahoo-mcp-token          # dev-mode static token

# Optional user identity mapping
USER_MAPPING={"alice@okta.example.com": "alice@company.onmicrosoft.com"}

# Production Entra credentials (leave blank for dev mode)
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=
MCP_CLIENT_ID=
```

---

## 7. Entra Auth in the Frontend (MSAL)

**File:** `frontend/src/authConfig.ts`
**File:** `frontend/src/main.tsx`

### Design decisions (hard-won through debugging)

#### Why loginRequest includes Chat.Read

```typescript
export const loginRequest = {
  scopes: ['openid', 'profile', 'email',
           `api://${VITE_ENTRA_CLIENT_ID}/Chat.Read`],
}
export const tokenRequest = {
  scopes: [`api://${VITE_ENTRA_CLIENT_ID}/Chat.Read`],
}
```

Including `Chat.Read` in `loginRequest` means MSAL acquires and caches the backend-scoped
token at sign-in.  Every subsequent `acquireTokenSilent(tokenRequest)` call returns
from cache without a network round-trip.

If `Chat.Read` is absent from `loginRequest`, MSAL issues a User.Read (Graph) token at
sign-in.  Later calls to `acquireTokenSilent(tokenRequest)` hit a different resource,
require a network call, and in some tenants trigger an interaction (popup) that breaks
the silent flow.

**Critical:** Do NOT mix resources in a single `loginRequest`.  MSAL rejects requests
that combine `api://<backend>/Chat.Read` and `User.Read` in the same scope array —
they are different resources and cannot be consented in a single token issuance.

#### Why initialize() must be awaited

```typescript
// frontend/src/main.tsx
const msalInstance = new PublicClientApplication(msalConfig)
await msalInstance.initialize()   // ← REQUIRED before any render
sessionStorage.removeItem('msal.interaction.status')  // clear stale lock
ReactDOM.createRoot(...).render(
  <MsalProvider instance={msalInstance}>...</MsalProvider>
)
```

MSAL v3+ requires `initialize()` to complete before any MSAL operations or render.
Without `await`, MSAL has not yet loaded its cache from `sessionStorage`, so
`accounts` is empty and silent token acquisition fails with
`uninitialized_public_client_application`.

The stale lock clear (`msal.interaction.status`) prevents `interaction_in_progress`
errors that occur when a previous popup was closed without completing (e.g. browser
crash, tab close during auth).

### 7.1 Token Acquisition for Backend API Calls

**File:** `frontend/src/components/ChatPanel.tsx`

```typescript
const getToken = useCallback(async (): Promise<string | null> => {
  if (!accounts.length) return null
  try {
    const r = await instance.acquireTokenSilent({
      ...tokenRequest,                // scopes: [api://<clientId>/Chat.Read]
      account: accounts[0],
    })
    return r.accessToken || null
  } catch {
    return null                       // no popup fallback — API calls work without auth
  }
}, [instance, accounts])
```

Returned `accessToken` has:
- `aud = api://<ENTRA_CLIENT_ID>` (the backend app registration)
- `scp = Chat.Read`
- `iss` — either v1 (`sts.windows.net`) or v2 depending on `requestedAccessTokenVersion`

**Requirement:** `requestedAccessTokenVersion` must be set to `2` on the backend app
registration (via Graph API `PATCH /applications/{id}` → `api.requestedAccessTokenVersion=2`).
Without this, tokens are issued as v1, which caused JWKS validation failures because
the v1 issuer (`sts.windows.net`) was not accepted by the middleware.

### 7.2 Graph Token vs App Token Handling in Middleware

**File:** `backend/app/core/auth/middleware.py` — `EntraJWTValidator.validate()`

The backend middleware has a dual validation path:

```python
# Path 1: Microsoft Graph tokens (aud starts with "https://graph.microsoft.com")
# Graph tokens are signed by Graph's own key infrastructure — NOT in the Entra OIDC JWKS.
# Verify claims only (iss, tid, exp); no JWKS signature check possible.
if aud in self._GRAPH_AUDIENCES or str(aud).startswith("https://graph.microsoft.com"):
    exp = unverified.get("exp", 0)
    if exp and exp < time.time():
        raise HTTPException(401, "Token expired")
    expected_v2 = f"https://login.microsoftonline.com/{self._tenant_id}/v2.0"
    expected_v1 = f"https://sts.windows.net/{self._tenant_id}/"
    if iss and iss not in (expected_v2, expected_v1):
        raise HTTPException(401, "Token issuer mismatch")
    if tid and tid != self._tenant_id:
        raise HTTPException(401, "Token tenant mismatch")
    return unverified   # ← claims-only, no signature verification

# Path 2: App tokens (aud = api://<clientId>) — full JWKS RS256 verification
# Accepts both v1 and v2 issuer forms (requestedAccessTokenVersion null/1/2)
expected_issuers = {
    f"https://login.microsoftonline.com/{self._tenant_id}/v2.0",
    f"https://sts.windows.net/{self._tenant_id}/",
}
claims = jwt.decode(token, rsa_key, algorithms=["RS256"],
                    audience=None,           # ← audience=None to avoid python-jose list rejection
                    options={"verify_aud": False, "verify_iss": False})
aud = claims.get("aud", "")
if aud and isinstance(aud, str) and aud not in self._audience:
    raise HTTPException(401, "Token audience mismatch")
iss = claims.get("iss", "")
if iss and iss not in expected_issuers:
    raise HTTPException(401, "Token issuer mismatch")
```

**Important implementation note:** `python-jose`'s `jwt.decode()` raises
`"audience must be a string or None"` when `audience` is a list, **even with
`verify_aud=False`**.  The workaround is `audience=None` combined with a manual
post-decode `aud` membership check.

---

## 8. Session Persistence and CosmosDB

**Files:**
- `backend/app/routes/chat.py` — stores sessions under `auth.user_id`
- `backend/app/core/routes/sessions.py` — lists sessions for the current user
- `backend/app/core/conversation/cosmos_session_store.py` — Cosmos operations

### user_id consistency requirement

Sessions are partitioned by `user_id` in Cosmos DB.  The `user_id` in both the write
path (chat route) and the read path (sessions list route) must use the **same** claim
preference order:

```python
# backend/app/core/auth/middleware.py — AuthContext.user_id
@property
def user_id(self) -> str:
    return (
        self.claims.get("preferred_username")   # UPN/email — first choice
        or self.claims.get("oid")               # object ID — fallback
        or self.claims.get("sub")               # subject — last resort
        or "anonymous"
    )

# backend/app/core/routes/sessions.py — _get_user_id() — MUST match above
def _get_user_id(authorization: str | None = Header(default=None)) -> str:
    ...
    return (
        payload.get("preferred_username")
        or payload.get("oid")
        or payload.get("sub")
        or "anonymous"
    )
```

**Bug that was fixed:** The sessions route originally only checked `oid` then `sub`,
skipping `preferred_username`.  The chat route uses `preferred_username` (e.g.
`alice@contoso.com`).  The result was chat sessions stored under
`alice@contoso.com` but the history list querying under `oid` (`a1b2c3d4-...`) —
no records found.  Both now use the same preference chain.

### Session document structure

```json
{
  "id": "<session-uuid>",
  "user_id": "alice@contoso.com",
  "title": "Show CPI and inflation trend...",
  "demo_mode": "okta-proxy",
  "created_at": "2026-04-14T16:24:26.982625+00:00",
  "updated_at": "2026-04-14T16:24:49.291099+00:00",
  "message_count": 2,
  "messages": [
    {
      "id": "<uuid>",
      "role": "user",
      "content": "Show CPI and inflation trend over the last 12 months",
      "agent": null,
      "traces": [],
      "timestamp": "2026-04-14T16:24:27.117741+00:00"
    },
    {
      "id": "<uuid>",
      "role": "assistant",
      "content": "### CPI Trend Over the Last 12 Months...",
      "agent": "economic_agent",
      "traces": [
        {"from_agent": "triage_agent", "to_agent": "economic_agent"}
      ],
      "timestamp": "2026-04-14T16:24:49.291099+00:00"
    }
  ]
}
```

---

## 9. Agent Framework: HandoffBuilder + require_per_service_call_history_persistence

**Files:**
- `backend/app/core/agents/base.py` — `BaseAgent.create()`
- `backend/app/core/workflows/base.py` — `build_triage_agent()`
- `backend/app/agents/esg_advisor.py` — direct `Agent(...)` constructor
- `backend/app/agents/github_intel.py` — `GitHubIntelAgent.create()`
- `backend/app/agents/market_intel.py` — `MarketIntelAgent.create()` (had it all along)

### Why the flag is required

`HandoffBuilder.build()` raises `ValueError` if any participant agent does not have
`require_per_service_call_history_persistence=True`:

```
ValueError: Handoff workflows require all participant agents to have
'require_per_service_call_history_persistence=True'. The following agents are
missing this setting: triage_agent, economic_agent, esg_advisor_agent,
github_intel_agent, portfolio_agent, private_data_agent.
```

With this flag set on each `Agent`, the framework stores `previous_response_id` on the
`Agent` **object** itself, not on the shared `FoundryChatClient`.  Each agent tracks
its own conversation chain independently.

### Why all agents share one FoundryChatClient

The `FoundryChatClient` must be **shared** (one instance per request, created by
`BaseOrchestrator._initialize()`).  Creating a separate client per agent causes:
- 7 independent `aiohttp.TCPConnector` connection pools per chat request
- Unclosed connector errors (`asyncio: Unclosed client session`)
- Request stalls in multi-idp mode (where mock-OIDC HTTP overhead adds extra init
  pressure, pushing the connection count past aiohttp's default pool size)

The correct design:
- **One** `FoundryChatClient` shared across all agents.
- `require_per_service_call_history_persistence=True` on each `Agent` to track
  `previous_response_id` per-agent.
- All agent `create_from_context()` methods use `ctx.client` (not `ctx.make_client()`).

### Where the flag is set

```python
# backend/app/core/agents/base.py — BaseAgent.create()
# Covers: EconomicDataAgent, PortfolioDataAgent, PrivateDataAgent
return Agent(
    client=client,
    name=cls.name,
    instructions=cls.system_message,
    tools=cls.build_tools(**kwargs),
    require_per_service_call_history_persistence=True,
)

# backend/app/core/workflows/base.py — build_triage_agent()
return Agent(
    client=self._client,
    name=self.triage_agent_name,
    instructions=self.triage_instructions,
    context_providers=context_providers or None,
    require_per_service_call_history_persistence=True,
)

# backend/app/agents/esg_advisor.py — direct Agent() constructor
return Agent(
    client=ctx.client,
    name=cls.name,
    ...
    require_per_service_call_history_persistence=True,
)

# backend/app/agents/github_intel.py — GitHubIntelAgent.create()
return Agent(
    client=client,
    name=cls.name,
    ...
    require_per_service_call_history_persistence=True,
)

# backend/app/agents/market_intel.py — MarketIntelAgent.create()
# Uses its own RawFoundryAgentChatClient (Foundry Prompt Agent, not FoundryChatClient)
agent_kwargs = {
    "client": market_client,
    "name": cls.name,
    "instructions": cls.system_message,
    "require_per_service_call_history_persistence": True,
}
```

---

## 10. SSE Streaming: Frontend Reader Loop

**File:** `frontend/src/components/ChatPanel.tsx` — `handleSend()`

### The [DONE] sentinel bug and fix

The backend sends `data: [DONE]\n\n` as the final SSE event after the stream ends.
The frontend originally had:

```typescript
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n')
  buffer = lines.pop() ?? ''

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const data = line.slice(6).trim()
    if (data === '[DONE]') break   // ← breaks for-loop only, NOT the while-loop
    ...
  }
}
```

`break` on `[DONE]` exits only the inner `for` loop over the current chunk's lines.
The outer `while (true)` keeps calling `reader.read()`, blocking until the TCP
connection closes.  The UI stayed in the loading state even after the full response
was received.

**Fix:** Use a `streamDone` flag:

```typescript
let streamDone = false
while (!streamDone) {
  const { done, value } = await reader.read()
  if (done) break
  buffer += decoder.decode(value, { stream: true })
  const lines = buffer.split('\n')
  buffer = lines.pop() ?? ''

  for (const line of lines) {
    if (!line.startsWith('data: ')) continue
    const data = line.slice(6).trim()
    if (data === '[DONE]') { streamDone = true; break }  // breaks both loops
    ...
  }
}
```

### Error event handling

The backend wraps the entire generator body in `except Exception`:

```python
# backend/app/routes/chat.py — event_stream()
try:
    async with PortfolioOrchestrator(settings) as orchestrator:
        async for event in gen:
            yield f"data: {json.dumps(event)}\n\n"
except Exception as exc:
    # Emit error event instead of re-raising.
    # Re-raising causes Starlette to abort the chunked transfer mid-stream,
    # giving browsers ERR_INCOMPLETE_CHUNKED_ENCODING.
    logger.exception("Unhandled error in chat event_stream: %s", exc)
    yield f"data: {json.dumps({'type': 'error', 'content': str(exc)})}\n\n"
finally:
    # Persist assistant message, close Cosmos store
    ...
    yield "data: [DONE]\n\n"
```

The frontend displays error events inline in the chat bubble:

```typescript
} else if (event.type === 'error' && event.content) {
  setMessages((prev) =>
    prev.map((m) =>
      m.id === assistantId
        ? { ...m, content: m.content + `\n\n_Error: ${event.content}_` }
        : m,
    ),
  )
}
```

---

## 11. Environment Variables Reference (Demo Modes)

### Backend (.env)

| Variable | Default | Description |
|---|---|---|
| `MOCK_OIDC_URL` | `http://localhost:8889` | Mock OIDC server base URL (`mock_oidc_url` in Settings) |
| `OKTA_PROXY_URL` | `http://localhost:8003` | Okta proxy base URL (`okta_proxy_url` in Settings) |
| `PORTFOLIO_MCP_CLIENT_ID` | `""` | Portfolio MCP app reg client ID (audience for mock tokens) |
| `YAHOO_MCP_CLIENT_ID` | `""` | Yahoo Finance MCP app reg client ID |
| `ENTRA_TENANT_ID` | `""` | If set, activates production auth paths on backend |
| `ENTRA_BACKEND_CLIENT_ID` | `""` | Backend API app reg (JWT audience for incoming tokens) |
| `ENTRA_CLIENT_SECRET` | `""` | Backend client secret for OBO exchange |

### Yahoo Finance MCP (.env)

| Variable | Required for multi-idp | Description |
|---|---|---|
| `TRUSTED_ISSUERS` | Yes | Comma-separated extra OIDC issuers; set to `http://localhost:8889` |
| `MCP_CLIENT_ID` | Yes | GUID that issued mock tokens must target as `aud` |
| `ENTRA_TENANT_ID` | For prod only | If absent, static token fallback only |
| `MCP_AUTH_TOKEN` | Dev | Static dev token for basic auth in dev mode |
| `JWKS_CACHE_TTL` | No | JWKS cache lifetime in seconds (default `3600`) |

### Portfolio MCP (.env)

Same as Yahoo Finance MCP above but with `portfolio.read` scope.

### Mock OIDC server (.env)

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8889` | Listen port |
| `TOKEN_EXPIRY_SECONDS` | `3600` | Token lifetime |

### Okta Proxy (.env)

| Variable | Required | Description |
|---|---|---|
| `OKTA_ISSUER` | Yes | Must match mock OIDC issuer = `http://localhost:8889` |
| `OKTA_AUDIENCE` | Yes | `api://<yahoo-mcp-client-id>` — must match mock token `aud` |
| `TARGET_MCP_URL` | Yes | Yahoo Finance MCP URL = `http://localhost:8001` |
| `TARGET_MCP_TOKEN` | Dev | Static bearer token to use when forwarding to MCP in dev mode |
| `USER_MAPPING` | No | JSON dict mapping Okta emails to Entra UPNs |

---

## 12. Startup Order for Local Demo

The following order avoids dependency failures:

```
1. 0_run_backend.bat       (FastAPI on :8000)
   Depends on: Cosmos DB endpoint, Foundry endpoint (env vars)

2. 1_run_frontend.bat      (Vite on :5173)
   Depends on: Nothing for startup; needs :8000 for chat

3. 2_run_mcp_portfolio.bat (Portfolio MCP on :8002)
   Depends on: Nothing for startup

4. 3_run_mcp_yahoo.bat     (Yahoo Finance MCP on :8001)
   Must be started BEFORE mock OIDC or proxy (otherwise JWKS fetch on first
   request may time out if trusted issuer is not yet up — but retries cleanly)

5. 6_run_mock_oidc.bat     (Mock OIDC on :8889)
   Required for multi-idp and okta-proxy modes
   Creates a NEW RSA keypair on every start — restart MCP servers after
   restarting mock OIDC so their JWKS cache is invalidated

6. 7_run_okta_proxy.bat    (Okta proxy on :8003)
   Required for okta-proxy mode only
   Must start AFTER mock OIDC (needs to discover the JWKS)

7. 5_run_a2a_esg.bat       (ESG A2A agent on :8010)  — optional
8. 4_run_aspire_dashboard.bat  (Aspire on :18888)    — optional (observability)
```

**After restarting mock OIDC:**
The mock OIDC server generates a new RSA key at startup.  Tokens issued before the
restart are signed with the old key and will fail JWKS verification.  The MCP servers
cache JWKS for `JWKS_CACHE_TTL` seconds (default 1 hour) — to force immediate cache
bust, restart the MCP servers or set `JWKS_CACHE_TTL=0` in their `.env` files.

### `entra-agent` mode: what to say during the demo

The Agent ID mode works locally but uses a **stand-in service principal** (`finagents`)
instead of a genuine Foundry-provisioned agent identity.  This is expected and intentional.

**What to say:** *"In this mode the backend authenticates as the agent itself — no user
OBO, no user context in the token.  The MCP server validates the token is from our
registered agent using OID pinning.  Locally we use a stand-in SP; in production on
Container Apps, DefaultAzureCredential picks up the Managed Identity federated to the
Foundry agent blueprint — that's when you'd see it in Entra's Agent ID sign-in logs."*

**What NOT to do during the demo:** do not open Entra > Agent ID > Sign-in logs and
expect to find entries — you won't, because `finagents` is not a first-class Agent ID
object.  Open Entra > Sign-in logs > Service principal sign-ins and filter by app name
`finagents` to show the actual sign-in activity.

---

## 13. Troubleshooting Reference

| Symptom | Likely cause | Fix |
|---|---|---|
| Multi-IDP: "Error: network error" in chat | Mock OIDC server not running | Start `6_run_mock_oidc.bat` |
| Multi-IDP: tokens fetched but MCP rejects | `MCP_CLIENT_ID` mismatch — mock token `aud` ≠ `api://<MCP_CLIENT_ID>` | Align `YAHOO_MCP_CLIENT_ID`/`PORTFOLIO_MCP_CLIENT_ID` in backend `.env` with `MCP_CLIENT_ID` in MCP server `.env` |
| Multi-IDP: JWKS key not found | Mock OIDC restarted, MCP JWKS cache stale | Restart MCP servers or set `JWKS_CACHE_TTL=0` |
| multi-idp tokens fetched but `TRUSTED_ISSUERS` not set on MCP | MCP falls back to Entra-only path; mock token rejected | Set `TRUSTED_ISSUERS=http://localhost:8889` in MCP `.env` |
| UI stuck loading (dots animated) after agent responds | `[DONE]` sentinel only broke inner `for` loop | Fixed: `streamDone` flag in ChatPanel.tsx reader loop |
| `ERR_INCOMPLETE_CHUNKED_ENCODING` | Unhandled exception escaped SSE generator, Starlette aborted chunked transfer | Fixed: `except Exception` in `chat.py` `event_stream()` |
| `ValueError: Handoff workflows require ... require_per_service_call_history_persistence` | Flag missing from one or more agents | Fixed: flag added to `BaseAgent.create()`, `build_triage_agent()`, `esg_advisor`, `github_intel` |
| Previous `previous_response_not_found` Foundry 400 | Flag removed previously to fix a different bug; agents sharing one client is fine WITH the flag | Flag re-added; all agents share `self._client` |
| Sessions not appearing in history panel | `sessions.py` used `oid` but chat stored by `preferred_username` | Fixed: `_get_user_id()` now uses same preference order as `AuthContext.user_id` |
| `audience must be a string or None` (python-jose) | Passing a list for `audience` to `jwt.decode()` even with `verify_aud=False` | Fixed: `audience=None` + manual `aud` check in middleware |
| `entra-agent` mode: no entries in Entra > Agent ID > Sign-in logs | `finagents` is a manually-created SP, not a Foundry-provisioned agent identity — `isAgent:true` flag is absent | Expected locally. Show auth activity under Entra > Sign-in logs > Service principal sign-ins, filtered by app name `finagents` |
| `entra-agent` mode: UI stuck loading after MCP tool call | `DefaultAzureCredential` falling through to `AzureCliCredential` re-spawns `az` subprocess on each token refresh; Windows ProactorEventLoop IOCP contention can delay follow-up Foundry LLM call | Fixed: credential instance cached in `AgentIdentityAuth`; `asyncio.timeout(120)` added as safety net in `BaseOrchestrator.run_handoff()` |
| `entra-agent` mode: MCP returns 403, logs show `oid mismatch` | `AGENT_IDENTITY_ID` in MCP `.env` doesn't match the OID of the SP `DefaultAzureCredential` resolved to | Run `az account show` — the OID in the token is your user OID, not `finagents`; log in as the SP or update `AGENT_IDENTITY_ID` to match |
| `AADSTS50013` OBO failure | Token being used as OBO assertion had `aud=https://graph.microsoft.com` | Fixed: `tokenRequest` now requests `api://<clientId>/Chat.Read`, not User.Read |
| `AADSTS500011` resource not found | `identifierUris` was empty on backend app reg | Fix: `az ad app update --identifier-uris api://<clientId>` |
| v1 issuer rejection (`sts.windows.net`) | `requestedAccessTokenVersion` was `null` → issued v1 tokens | Fix: PATCH app manifest to set `requestedAccessTokenVersion=2` |
| Okta-proxy mode: no response (hangs) | Proxy cannot reach Yahoo Finance MCP or mock OIDC not running | Verify :8001 and :8889 are up; check proxy `.env` config |
