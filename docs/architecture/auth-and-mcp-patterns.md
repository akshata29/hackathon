# Authentication & MCP Integration Patterns

This document covers the end-to-end authentication design and all three MCP integration
patterns implemented in the Portfolio Advisor backend.  It is intended for engineers
extending the system or adapting patterns to a new use-case.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Entra ID JWT Validation — The Middleware Layer](#2-entra-id-jwt-validation--the-middleware-layer)
3. [AuthContext — Design Decisions](#3-authcontext--design-decisions)
4. [The Three MCP Integration Patterns](#4-the-three-mcp-integration-patterns)
   - [Pattern 1a — Private MCP with OBO](#pattern-1a--private-mcp-with-obo-on-behalf-of)
   - [Pattern 1b — External Public MCP with API Key](#pattern-1b--external-public-mcp-with-backend-api-key)
   - [Pattern 2 — External Vendor MCP with Per-User OAuth](#pattern-2--external-vendor-mcp-with-per-user-oauth)
5. [End-to-End OBO Data Flow](#5-end-to-end-obo-data-flow)
6. [End-to-End GitHub OAuth Data Flow](#6-end-to-end-github-oauth-data-flow)
7. [Security Boundaries Summary](#7-security-boundaries-summary)
8. [Development vs Production Mode](#8-development-vs-production-mode)
9. [Environment Variables Reference](#9-environment-variables-reference)
10. [Per-Tool Audit Logging (MCP08)](#10-per-tool-audit-logging-mcp08--camp-4-telemetry)
11. [Prompt Injection Defense (MCP06)](#11-prompt-injection-defense--azure-ai-content-safety-mcp06)
12. [Supply Chain Security — Dependabot](#12-supply-chain-security--dependabot-mcp03mcp04)
13. [Cross-IDP Single Sign-On — Okta + Entra + MCP](#13-cross-idp-single-sign-on--okta--entra--mcp)
    - [Option A — APIM Token Exchange Policy](#option-a--apim-token-exchange-policy-no-code-changes)
    - [Option B — Multi-IDP Trust on MCP Server](#option-b--multi-idp-trust-on-mcp-server-already-implemented)
    - [Option C — Okta-to-Entra Token Exchange Proxy](#option-c--okta-to-entra-token-exchange-proxy-implemented-in-this-repo)
    - [Option D — Entra External Identities Federation with Okta](#option-d--entra-external-identities-federation-with-okta-strategic)

---

## 1. Architecture Overview

```
Browser (React SPA + MSAL)
        |
        |  Bearer <Entra access token>   (audience = backend API app reg)
        v
FastAPI Backend  [backend/app/]
        |
        |-- Validates JWT via JWKS .................. middleware.py
        |-- Extracts AuthContext (claims + raw token) middleware.py
        |-- Routes to orchestrator .................. routes/chat.py
        |
        +------ Pattern 1a: Private MCP ---------> OBO exchange (obo.py)
        |         portfolio-db, yahoo-finance            |
        |         (OBO token: audience = MCP app reg)    |
        |                                                v
        |                                        FastMCP server (entra_auth.py)
        |
        +------ Pattern 1b: External Public MCP -> Backend API key in URL/header
        |         Alpha Vantage MCP                 (no user identity propagated)
        |
        +------ Pattern 2: External Vendor MCP --> Per-user OAuth token (Cosmos)
                  GitHub MCP (api.githubcopilot.com)
                  (token retrieved from vendor-oauth-tokens container)
```

The critical insight driving the design: **a single incoming Entra Bearer token cannot
be forwarded as-is to downstream services**.  Its audience is locked to the backend API
application.  Each downstream system requires its own identity proof:

| Downstream | Accepted credential | Why |
|---|---|---|
| Private internal MCP | OBO-exchanged JWT (audience = MCP app reg) | Entra tenant, controlled app registration |
| External public MCP (Alpha Vantage) | API key embedded in URL | Third-party SaaS, no Entra integration |
| External vendor MCP (GitHub) | GitHub OAuth2 access token (per user) | GitHub's own identity system; never accepts Entra tokens |

---

## 2. Entra ID JWT Validation — The Middleware Layer

**File:** `backend/app/core/auth/middleware.py`

### How token validation works

The `EntraJWTValidator` class performs full RS256 signature verification using the
tenant's JSON Web Key Set (JWKS).  The flow on first request:

```
request arrives with Authorization: Bearer <token>
   |
   v
EntraJWTValidator.validate(token)
   |-- jwt.get_unverified_header(token)  -> extract kid (key ID)
   |-- GET https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration
   |       -> jwks_uri (cached)
   |-- GET {jwks_uri}  -> keyset (cached until key rotation)
   |-- find key matching kid in keyset
   |-- jose.jwt.decode(token, rsa_key, algorithms=["RS256"],
   |                   audience=entra_backend_client_id,
   |                   issuer="https://login.microsoftonline.com/{tenant}/v2.0")
   |
   v
returns claims dict  OR  raises HTTP 401
```

JWKS is cached at module level.  On a `kid` mismatch (Entra key rotation), the cache
is invalidated and the keyset is re-fetched on the next request.

### The three dependency options

Three FastAPI dependency functions are provided, each with a different trust level:

```python
# 1. Hard auth — raises 401 if no/invalid token.  Use for any route
#    that touches user data.
claims = Depends(require_authenticated_user)   # returns dict[str, Any]

# 2. Soft auth — returns None for unauthenticated callers.  Use for
#    endpoints that are anonymous-safe but enriched when authenticated.
claims = Depends(maybe_authenticated_user)     # returns dict | None

# 3. Full context — returns AuthContext (claims + raw token string).
#    Use when the route also needs to perform OBO exchange or store
#    a vendor OAuth token.  This is the preferred option for chat routes.
auth = Depends(require_auth_context)           # returns AuthContext
```

**Design decision:** `require_auth_context` was introduced specifically because
the OBO flow requires the **raw** Bearer string (the signed JWT bytes) to be
forwarded to `azure.identity.aio.OnBehalfOfCredential`.  Using only `claims`
loses the original token — claims extracted by `jose.jwt.decode` cannot be
re-assembled into a valid signed JWT.

---

## 3. AuthContext — Design Decisions

**File:** `backend/app/core/auth/middleware.py` — `AuthContext` dataclass

```python
@dataclass
class AuthContext:
    claims: dict[str, Any]   # validated JWT payload
    raw_token: str           # original Bearer string (needed for OBO)

    @property
    def user_id(self) -> str:
        # Preference: preferred_username (UPN/email) > oid > sub > "anonymous"
        ...
```

### Why a dataclass instead of two separate dependencies?

The naive approach would be two injection points:

```python
async def chat_message(
    claims: dict = Depends(require_authenticated_user),
    credentials: HTTPAuthorizationCredentials = Security(HTTPBearer()),
):
    raw_token = credentials.credentials  # redundant work; re-extracts the header
```

This validates the token **once** in `require_authenticated_user`, then reads the raw
string again from the injection of `HTTPBearer`.  It also means every route must
declare two parameters when it needs OBO.

`AuthContext` packages both outputs of a **single** validation pass.  `require_auth_context`
is the only place where `EntraJWTValidator.validate()` is called; the result — claims plus
raw token — travels together as one object for the rest of the request lifecycle.

### user_id preference order

`preferred_username` (the UPN, typically `user@company.com`) is chosen over `oid`
(object ID) as the default user identifier because:

- It is human-readable in logs and Cosmos partition keys.
- It matches what the portfolio MCP server uses in its SQLite RLS table.
- It is stable within a tenant (a user cannot change their UPN without IT involvement).

`oid` is used as the fallback for accounts that do not emit `preferred_username`
(e.g. service principals, guest accounts) and as the partition key in the
`vendor-oauth-tokens` Cosmos container (where a stable opaque ID is preferable to
a mutable email).

### Dev mode behaviour

When `ENTRA_TENANT_ID` is not configured, `require_auth_context` skips JWKS validation
and instead base64-decodes the JWT payload without verifying the signature
(`_decode_claims_unsafe`).  This allows local development with a real MSAL token from
a browser session while avoidng the need to configure full Entra during early development.

If no token is present at all, a stable dev identity is returned:

```python
AuthContext(
    claims={"sub": "dev", "oid": "dev", "preferred_username": "dev@localhost"},
    raw_token="",
)
```

This ensures the same code paths execute locally — session stores, Cosmos partitioning,
and agent routing all behave identically.  The OBO module detects the empty `raw_token`
and switches to the static-token fallback.

---

## 4. The Three MCP Integration Patterns

### Pattern 1a — Private MCP with OBO (On-Behalf-Of)

**Used by:** `PortfolioDataAgent`, `PrivateDataAgent`
**Files:** `backend/app/core/auth/obo.py`, `backend/app/agents/portfolio_data.py`

#### When to use this pattern

The MCP server:
- Lives inside your Azure tenant (Container App, AKS, or VM).
- Has its own **Entra app registration** (`MCP_CLIENT_ID` env var on the server).
- Should only serve data for the **currently authenticated user** (row-level security).
- Can validate an Entra JWT.

#### How OBO works

The Entra On-Behalf-Of flow allows the backend service (acting as a confidential client)
to exchange the user's incoming token for a new token whose **audience** is the downstream
MCP server.  The downstream server validates this new token and extracts the user's `oid`
for row-level security — no separate `X-User-Id` header required in production.

```
User's Entra token               OBO-exchanged token
aud: api://<backend-client-id>  ->  aud: api://<mcp-client-id>
oid: <user oid>                      oid: <user oid>   (preserved)
scp: <delegated scopes>              scp: portfolio.read
```

The exchange happens at `https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token`
using the `urn:ietf:params:oauth:grant-type:jwt-bearer` grant type.

#### Code walkthrough

**Step 1 — Route injects AuthContext:**

```python
# backend/app/routes/chat.py
@router.post("/message")
async def chat_message(
    request: ChatRequest,
    auth: AuthContext = Depends(require_auth_context),
):
    user_id = auth.user_id
    raw_token = auth.raw_token          # <-- the signed Entra JWT
    ...
    gen = orchestrator.run_handoff(
        message=request.message,
        session_id=session_id,
        user_token=user_id,
        raw_token=raw_token,            # <-- forwarded through orchestrator
        history=prior_messages,
    )
```

**Step 2 — Orchestrator threads raw_token to agent factory:**

```python
# backend/app/core/workflows/base.py  (BaseOrchestrator)
async def run_handoff(self, ..., raw_token=None):
    ...
    agents = self.build_specialist_agents(user_token=user_token, raw_token=raw_token)
```

```python
# backend/app/workflows/portfolio_workflow.py  (PortfolioOrchestrator)
def build_specialist_agents(self, user_token=None, raw_token=None):
    return [
        PortfolioDataAgent.create(
            self._client,
            raw_token=raw_token,         # <-- passed to build_tools()
            settings=self._settings,
            ...
        ),
        ...
    ]
```

**Step 3 — Agent builds OBO-authenticated HTTP client:**

```python
# backend/app/agents/portfolio_data.py
@classmethod
def build_tools(cls, raw_token=None, settings=None, ...):
    http_client = build_obo_http_client(
        settings=settings,
        raw_token=raw_token,
        mcp_client_id=settings.portfolio_mcp_client_id,
        scope_name="portfolio.read",
        fallback_bearer=mcp_auth_token,
    )
    return [
        MCPStreamableHTTPTool(
            name="PortfolioData",
            url=f"{portfolio_mcp_url}/mcp",
            http_client=http_client,     # <-- all requests go through OBOAuth
        )
    ]
```

**Step 4 — OBOAuth httpx handler performs the exchange:**

```python
# backend/app/core/auth/obo.py  (OBOAuth.async_auth_flow)
async def async_auth_flow(self, request: httpx.Request):
    if not self._token:
        credential = OnBehalfOfCredential(
            tenant_id=self._tenant_id,
            client_id=self._client_id,       # backend app reg
            client_secret=self._client_secret,
            user_assertion=self._user_assertion,  # the user's raw Entra JWT
        )
        self._token = await credential.get_token(self._scope)
                                             # scope = api://<mcp-client-id>/portfolio.read

    request.headers["Authorization"] = f"Bearer {self._token}"
    response = yield request

    if response.status_code == 401:          # auto-refresh on expiry
        self._token = None
        self._token = await self._acquire()
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request
```

**Step 5 — MCP server validates the OBO token:**

```python
# mcp-servers/portfolio-db/entra_auth.py  (EntraTokenVerifier)
# Validates incoming Bearer token:
#   - audience must equal api://<MCP_CLIENT_ID>
#   - issuer must equal https://login.microsoftonline.com/{ENTRA_TENANT_ID}/v2.0
#   - signature verified against JWKS
# On success: returns claims dict
# On failure: returns None -> FastMCP rejects with 401

# Inside MCP tool:
def get_user_id_from_request():
    # Extracts oid / preferred_username from validated claims
    # Used as the RLS parameter in every SQL query
    return claims.get("preferred_username") or claims.get("oid")
```

#### Required Entra app registrations

| App registration | Purpose | Env var |
|---|---|---|
| Frontend SPA | Issues tokens via MSAL | `ENTRA_CLIENT_ID` |
| Backend API | Token audience for incoming requests | `ENTRA_BACKEND_CLIENT_ID` |
| Portfolio MCP | OBO target audience + scope definition | `PORTFOLIO_MCP_CLIENT_ID` |
| Yahoo Finance MCP | OBO target audience + scope definition | `YAHOO_MCP_CLIENT_ID` |

The `scripts/post-provision.ps1` script automates creation of the backend and MCP
app registrations with the correct API scope definitions.

---

### Pattern 1b — External Public MCP with Backend API Key

**Used by:** `EconomicDataAgent` (Alpha Vantage)
**File:** `backend/app/agents/economic_data.py`

#### When to use this pattern

The MCP server:
- Is a third-party public SaaS (no Entra integration possible).
- Does not return user-specific confidential data.
- Authenticates callers via a single API key shared across all backend requests.

#### Implementation

```python
# backend/app/agents/economic_data.py
class EconomicDataAgent(BaseAgent):

    @classmethod
    def build_tools(cls, alphavantage_api_key: str = "", ...):
        if alphavantage_api_key:
            # Use the officially hosted Alpha Vantage remote MCP endpoint.
            # The API key is an URL query parameter — no user identity propagated.
            from agent_framework import MCPStreamableHTTPTool
            return [
                MCPStreamableHTTPTool(
                    url=f"https://mcp.alphavantage.co/mcp?apikey={alphavantage_api_key}",
                    ...
                )
            ]
        else:
            # Fallback: call Alpha Vantage REST API directly via FunctionTools.
            # Used in environments where the remote MCP endpoint is unavailable.
            return _build_av_tools(api_key=alphavantage_api_key)
```

**Security note:** The API key is stored in Key Vault and injected via the
`ALPHAVANTAGE_API_KEY` environment variable.  It is a **backend secret** — it is
never included in any response to the frontend and never logged.  Because this agent
returns only public economic data (Fed rates, GDP, etc.) there is no row-level security
requirement.

---

### Pattern 2 — External Vendor MCP with Per-User OAuth

**Used by:** `GitHubIntelAgent`
**Files:** `backend/app/core/auth/vendor_oauth_store.py`, `backend/app/routes/github_auth.py`, `backend/app/agents/github_intel.py`

#### When to use this pattern

The MCP server:
- Is operated by an external vendor (GitHub, Salesforce, ServiceNow...).
- Implements its own OAuth2 Authorization Server (not Entra).
- Requires a **per-user** access token (not a shared service credential).
- Will never accept an Entra token — it has no relationship to your Azure tenant.

#### Full flow

```
User clicks "Connect GitHub" in NavBar
        |
        v
frontend: GET /api/auth/github   (with Entra Bearer)
        |
        | require_auth_context validates Entra JWT -> extracts user_oid
        |
        v  HMAC-signed state = {oid, timestamp}
Redirect 302 -> https://github.com/login/oauth/authorize
                  ?client_id=<github-oauth-app>
                  &redirect_uri=<backend>/api/auth/github/callback
                  &scope=public_repo read:user
                  &state=<hmac_state>
        |
        | User authorizes in GitHub
        v
GitHub redirects to GET /api/auth/github/callback?code=<code>&state=<hmac_state>
        |
        | _verify_state(): HMAC check + timestamp expiry (10 min window)
        | recovers user_oid from state (no session cookie needed)
        |
        | POST https://github.com/login/oauth/access_token
        |     body: client_id, client_secret, code, redirect_uri
        |     -> { access_token, token_type, scope }
        |
        v
GitHubTokenStore.store_token(user_oid, access_token, scope)
        |  Cosmos DB: vendor-oauth-tokens container
        |  Document: { id: "<oid>-github", user_oid, vendor, access_token, ... }
        |
Redirect 302 -> <frontend>?github_connected=true
        |
        v
NavBar: setGithubConnected(true)  (detects query param, removes it from URL)
```

#### State parameter CSRF protection

Standard OAuth2 state parameters use a session cookie to tie the initiating request
to the callback.  This backend is stateless (no server-side sessions), so the state
parameter is self-describing and cryptographically signed:

```python
# backend/app/routes/github_auth.py

def _make_state(user_oid: str, secret: str) -> str:
    payload = json.dumps({"oid": user_oid, "ts": int(time.time())})
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload.encode().hex()}.{sig}"

def _verify_state(state: str, secret: str, max_age_seconds: int = 600) -> str:
    hex_payload, sig = state.split(".", 1)
    payload_bytes = bytes.fromhex(hex_payload)
    expected_sig = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise HTTPException(status_code=400, detail="Invalid OAuth state (tampered)")
    data = json.loads(payload_bytes)
    if int(time.time()) - data["ts"] > max_age_seconds:
        raise HTTPException(status_code=400, detail="OAuth state expired")
    return data["oid"]
```

`hmac.compare_digest` is used instead of `==` to prevent timing attacks.
The 10-minute expiry window closes replay attacks from intercepted state values.

#### Token storage (VendorOAuthStore)

```python
# backend/app/core/auth/vendor_oauth_store.py

class VendorOAuthStore:
    """
    Cosmos DB-backed per-user OAuth token store.
    Container: vendor-oauth-tokens
    Partition key: /user_oid
    Document: { id: "<oid>-<vendor>", user_oid, vendor, access_token,
                refresh_token, scope, stored_at, expires_at }
    """

    async def store_token(self, user_oid, access_token, ...):
        doc = {
            "id": f"{user_oid}-{self._vendor}",
            "user_oid": user_oid,
            "vendor": self._vendor,
            "access_token": access_token,
            ...
        }
        await container.upsert_item(doc)   # idempotent — re-auth replaces doc

    async def retrieve_token(self, user_oid) -> str | None:
        item = await container.read_item(
            item=f"{user_oid}-{self._vendor}",
            partition_key=user_oid,
        )
        return item.get("access_token")

    async def delete_token(self, user_oid):
        await container.delete_item(
            item=f"{user_oid}-{self._vendor}",
            partition_key=user_oid,
        )


class GitHubTokenStore(VendorOAuthStore):
    def __init__(self, settings: Settings):
        super().__init__(settings, vendor="github")
```

The `vendor-oauth-tokens` Cosmos container is explicitly provisioned in
`infra/modules/cosmosdb.bicep` (partition key `/user_oid`, no TTL — tokens are
revoked explicitly via `DELETE /api/auth/github`).

#### Agent — live vs fallback tool

```python
# backend/app/agents/github_intel.py

class GitHubIntelAgent(BaseAgent):

    @classmethod
    def build_tools(cls, github_token: str | None = None, **kwargs) -> list:
        if github_token:
            # Live path: attach the per-user GitHub token as Bearer.
            # The remote GitHub MCP validates it against GitHub's own API.
            http_client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "X-GitHub-MCP-Toolsets": "repos,issues",  # read-only subset
                }
            )
            return [MCPStreamableHTTPTool(url="https://api.githubcopilot.com/mcp/",
                                          http_client=http_client)]
        else:
            # Graceful degradation — no exception thrown.
            # The tool returns a message prompting the user to connect GitHub.
            async def github_not_connected(company: str) -> str:
                return (
                    "GitHub is not connected for this account. "
                    "Visit /api/auth/github to authorize."
                )
            return [FunctionTool(name="github_engineering_intel",
                                 func=github_not_connected)]
```

#### Sync/async boundary in the workflow

`build_specialist_agents` is a **synchronous** method (the Agent Framework requires it).
Token retrieval from Cosmos DB is **asynchronous**.  The solution is a pre-fetch pattern
in the overridden `run_handoff` / `run_comprehensive`:

```python
# backend/app/workflows/portfolio_workflow.py

class PortfolioOrchestrator(BaseOrchestrator):

    async def run_handoff(self, ..., user_token=None, ...):
        # Pre-fetch BEFORE the sync build_specialist_agents is called.
        self._github_token = await self._fetch_github_token(user_token)
        async for event in super().run_handoff(...):
            yield event

    def build_specialist_agents(self, user_token=None, raw_token=None):
        github_token = getattr(self, "_github_token", None)  # read pre-fetched value
        return [
            ...
            GitHubIntelAgent.create(self._client, github_token=github_token, ...),
        ]
```

This keeps `build_specialist_agents` synchronous (as required by the framework) while
still allowing the async Cosmos lookup to happen correctly within the async lifecycle.

---

## 5. End-to-End OBO Data Flow

Sequence for a chat message that queries the portfolio agent in production:

```
1.  User type: "Show my top 10 holdings"
    Browser sends:  POST /api/chat/message
                    Authorization: Bearer <Entra token A>
                    body: { message, session_id }

2.  require_auth_context (middleware.py):
    a. EntraJWTValidator fetches JWKS from Entra (cached after first call)
    b. RS256 verify: audience=entra_backend_client_id, issuer=login.microsoftonline.com/...
    c. Returns AuthContext { claims: {..., oid, preferred_username}, raw_token: <token A> }

3.  chat_message route (routes/chat.py):
    user_id   = auth.user_id          -> "alice@contoso.com"
    raw_token = auth.raw_token        -> <token A>
    Calls orchestrator.run_handoff(user_token="alice@contoso.com", raw_token=<token A>)

4.  BaseOrchestrator.run_handoff (core/workflows/base.py):
    - HandoffBuilder with triage + 5 specialist agents
    - triage agent decides: route to portfolio_agent
    - calls build_specialist_agents(user_token="alice@...", raw_token=<token A>)

5.  PortfolioDataAgent.build_tools (agents/portfolio_data.py):
    - build_obo_http_client(raw_token=<token A>, mcp_client_id=<portfolio_reg>)
    - Returns httpx.AsyncClient(auth=OBOAuth(...))
    - MCPStreamableHTTPTool wraps this client

6.  When agent makes first MCP call, OBOAuth.async_auth_flow fires:
    a. OnBehalfOfCredential.get_token(scope="api://<portfolio_mcp_client_id>/portfolio.read")
       -> POST https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token
          grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
          client_id=<backend_client_id>
          client_secret=<backend_client_secret>
          assertion=<token A>           <- user's original token
          requested_token_use=on_behalf_of
          scope=api://<portfolio_mcp_client_id>/portfolio.read
       <- { access_token: <token B> }   <- OBO token, aud=portfolio MCP app reg

    b. Adds header:  Authorization: Bearer <token B>

7.  Portfolio MCP server (mcp-servers/portfolio-db/server.py):
    a. entra_auth.EntraTokenVerifier.verify_token(<token B>)
       -> JWKS validate: audience=api://<MCP_CLIENT_ID>, issuer=login.microsoftonline.com
       -> returns claims
    b. get_user_id_from_request() -> "alice@contoso.com"   (from preferred_username claim)
    c. SQL:  SELECT * FROM holdings WHERE user_id = 'alice@contoso.com'
    d. Returns alice's holdings only — no other user's data is accessible

8.  Agent synthesises response, streams back via SSE to browser.
```

**Key security properties:**
- Token A is never forwarded to any downstream service.
- Token B is scoped to a single MCP server — it cannot be used against any other service.
- Row-level security is enforced by the MCP server independently — the backend cannot
  override it by modifying headers (the OBO token carries the user identity).

---

## 6. End-to-End GitHub OAuth Data Flow

#### First-time connection

```
1.  User clicks "Connect GitHub" in NavBar
    Frontend: GET /api/auth/github
              Authorization: Bearer <Entra token A>

2.  require_auth_context resolves user_oid = "a1b2c3d4..."  (stable oid claim)

3.  github_auth.github_oauth_initiate:
    state = _make_state(user_oid="a1b2c3...", secret=GITHUB_OAUTH_CLIENT_SECRET)
    Redirect 302 -> https://github.com/login/oauth/authorize
                      ?client_id=...&scope=public_repo read:user&state=...

4.  GitHub: user sees "Portfolio Advisor wants to access your public repos"
    User clicks Authorize.
    GitHub redirects: GET /api/auth/github/callback?code=<one_time_code>&state=<state>

5.  github_auth.github_oauth_callback:
    user_oid = _verify_state(state, GITHUB_OAUTH_CLIENT_SECRET)
               -> HMAC-OK, timestamp < 10 min -> returns "a1b2c3d4..."

    POST https://github.com/login/oauth/access_token
         client_id, client_secret, code, redirect_uri
    <- { access_token: "gho_...", scope: "public_repo,read:user", token_type: "bearer" }

6.  GitHubTokenStore.store_token(user_oid="a1b2c3...", access_token="gho_...")
    -> Cosmos upsert: { id: "a1b2c3...-github", user_oid: "a1b2c3...",
                        vendor: "github", access_token: "gho_..." }

7.  Redirect 302 -> <frontend>?github_connected=true
    NavBar useEffect detects param, calls setGithubConnected(true), strips param from URL
```

#### Subsequent chat message using GitHub data

```
1.  User: "Analyze MSFT's engineering health on GitHub"
    POST /api/chat/message  with Entra Bearer

2.  require_auth_context -> user_oid = "a1b2c3d4..."

3.  PortfolioOrchestrator.run_handoff:
    self._github_token = await _fetch_github_token("a1b2c3d4...")
    -> GitHubTokenStore.retrieve_token("a1b2c3d4...")
    -> Cosmos read: { access_token: "gho_..." }
    -> self._github_token = "gho_..."

4.  build_specialist_agents:
    GitHubIntelAgent.create(client, github_token="gho_...")
    -> build_tools(github_token="gho_...")
    -> MCPStreamableHTTPTool(
           url="https://api.githubcopilot.com/mcp/",
           http_client=AsyncClient(headers={
               "Authorization": "Bearer gho_...",
               "X-GitHub-MCP-Toolsets": "repos,issues",
           })
       )

5.  Triage routes to github_intel_agent.
    Agent calls: search_repositories(org="microsoft"), list_commits(repo="vscode"), ...
    GitHub MCP server validates gho_... token against its own API.
    Returns: public repo data, commit counts, open issue statistics.

6.  Agent synthesises: "MSFT/vscode: 89K stars, 4.2K commits last month..."
    Streamed back via SSE.
```

---

## 7. Security Boundaries Summary

| Concern | Mechanism | File |
|---|---|---|
| Incoming JWT signature | RS256 JWKS validation | `core/auth/middleware.py` |
| Downstream MCP user identity | OBO token (aud = MCP app reg) | `core/auth/obo.py` |
| MCP row-level security | oid / preferred_username from OBO claims | `mcp-servers/*/entra_auth.py` |
| Vendor OAuth CSRF | HMAC-SHA256 signed state (stateless) | `routes/github_auth.py` |
| Vendor token storage | Cosmos DB, partition by user_oid | `core/auth/vendor_oauth_store.py` |
| Vendor token isolation | Each user reads/writes only their own partition | Cosmos partition key design |
| API key for public MCPs | Backend env var / Key Vault, never in responses | `config.py` + Key Vault |
| Dev mode bypass | Only when ENTRA_TENANT_ID is unset | `middleware.py` + `obo.py` |
| Prompt injection guardrail | `check_user_message` before workflow | `core/guardrails/policy.py` |
| MCP tool argument injection | Azure AI Content Safety on all string args | `mcp-servers/*/entra_auth.py` |
| Technical injection detection (Camp 3) | `check_injection_patterns()` — shell/SQL/path traversal/template regex before Content Safety | `mcp-servers/*/entra_auth.py` |
| Jailbreak / indirect prompt injection (Camp 3) | `check_prompt_shields()` — Azure Content Safety Prompt Shields REST endpoint (`/contentsafety/text:shieldPrompt`) | `mcp-servers/*/entra_auth.py` |
| Output credential leakage (Camp 3) | `scan_output_credentials()` — regex + Shannon entropy redaction on tool responses; applied to `get_news` | `mcp-servers/*/entra_auth.py` |
| MCP per-tool audit trail | `audit_log()` with `extra={"custom_dimensions": ...}` per tool invocation | `mcp-servers/*/entra_auth.py` |
| Structured security event telemetry (Camp 4) | `SecurityEventType` + `log_security_event()` emit INJECTION_BLOCKED / CREDENTIAL_DETECTED / INPUT_CHECK_PASSED events as KQL-queryable custom dimensions | `mcp-servers/*/entra_auth.py` |
| Azure Monitor OTel on MCP servers (Camp 4) | `configure_azure_monitor()` on startup; unified telemetry with backend in one Application Insights instance | `mcp-servers/*/server.py` |
| Supply chain vulnerabilities | Dependabot weekly scans (pip + npm) | `.github/dependabot.yml` |
| OAuth 2.1 client auto-discovery | `/.well-known/oauth-protected-resource` (RFC 9728 PRM) | `mcp-servers/*/entra_auth.py` (`make_prm_app()`) |
| 401 auth challenge header | `WWW-Authenticate: Bearer resource_metadata="..."` on every 401/403 | `mcp-servers/*/entra_auth.py` (`PRMAuthenticateMiddleware`) |
| Multi-IDP token acceptance | Trusted OIDC issuers whitelist (Entra + configurable) | `mcp-servers/*/entra_auth.py` (`MultiIDPTokenVerifier`) |

**Cross-user data access is structurally prevented**: the OBO token carries the oid claim;
the MCP server uses it as the SQL WHERE clause parameter.  There is no code path that could
produce another user's oid in that claim — it comes from the cryptographically verified JWT.

---

## 8. Development vs Production Mode

The system detects dev mode by checking `settings.entra_tenant_id`:

| Component | Dev mode (ENTRA_TENANT_ID not set) | Production |
|---|---|---|
| JWT validation | Unsafe base64 decode, no signature check | Full JWKS RS256 |
| Missing token | Returns `dev@localhost` identity | HTTP 401 |
| OBO exchange | Skipped; uses static `MCP_AUTH_TOKEN` | Full Entra OBO |
| MCP auth (server side) | Static token comparison | JWKS JWT validation |
| X-User-Id header | Included (needed for RLS without OBO) | Omitted (oid in OBO token) |
| Portfolio RLS | SQLite `WHERE user_id = 'dev@localhost'` | SQLite `WHERE user_id = <oid>` |

This layered fallback means the entire system runs locally without Entra credentials and
still exercises the correct code paths.  The only difference is the identity source — in
dev that is a fixed string, in production it is a cryptographically verified claim.

---

## 9. Environment Variables Reference

### Authentication (core)

| Variable | Description | Required in prod |
|---|---|---|
| `ENTRA_TENANT_ID` | Azure tenant ID | Yes |
| `ENTRA_CLIENT_ID` | Frontend SPA app registration client ID | Yes |
| `ENTRA_BACKEND_CLIENT_ID` | Backend API app registration client ID (JWT audience) | Yes |
| `ENTRA_CLIENT_SECRET` | Backend app reg client secret (used in OBO exchange) | Yes |
| `PORTFOLIO_MCP_CLIENT_ID` | Portfolio MCP app registration client ID | Yes |
| `YAHOO_MCP_CLIENT_ID` | Yahoo Finance MCP app registration client ID | Yes |

### MCP servers (Pattern 1a — private)

| Variable | Description |
|---|---|
| `PORTFOLIO_MCP_URL` | Internal Container App URL of portfolio-db MCP server |
| `YAHOO_MCP_URL` | Internal Container App URL of yahoo-finance MCP server |
| `MCP_AUTH_TOKEN` | Static token for dev-mode MCP auth (not used in production) |
| `RESOURCE_URL` | Public-facing HTTPS URL of the MCP server (used in PRM endpoint and `WWW-Authenticate` headers); inferred from request host if unset |

### MCP servers (Pattern 1b — public)

| Variable | Description |
|---|---|
| `ALPHAVANTAGE_API_KEY` | Alpha Vantage API key (stored in Key Vault in production) |

### MCP servers (Pattern 2 — vendor OAuth)

| Variable | Description |
|---|---|
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth App client ID |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth App client secret (Key Vault in production) |
| `GITHUB_OAUTH_REDIRECT_URI` | Callback URL registered in the GitHub OAuth App |

### MCP security features

| Variable | Description |
|---|---|
| `AZURE_CONTENT_SAFETY_ENDPOINT` | Azure AI Content Safety endpoint URL (omit to disable; safe to leave unset in dev) |
| `TRUSTED_ISSUERS` | Comma-separated additional OIDC issuer URLs (e.g. Okta); Entra is always trusted |
| `JWKS_CACHE_TTL` | JWKS key cache lifetime in seconds (default: `3600`) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insights connection string; when set, activates Azure Monitor OpenTelemetry on MCP server startup for unified telemetry with the backend (Camp 4) |

---

## 10. Per-Tool Audit Logging (MCP08) — Camp 4 Telemetry

Every MCP tool invocation emits a structured log entry via `audit_log()` in
`entra_auth.py` inside a `try/finally` block that executes even if the tool raises.

When `APPLICATIONINSIGHTS_CONNECTION_STRING` is set and Azure Monitor OpenTelemetry
is active, entries use `extra={"custom_dimensions": entry}` so Application Insights
stores each field as a queryable dimension.  This enables KQL queries such as:

```kql
// Failed tool attempts by user
traces
| where customDimensions.outcome == "denied"
| summarize FailedAttempts = count() by tostring(customDimensions.user_id), tostring(customDimensions.tool)
| order by FailedAttempts desc

// Security events by type
traces
| where customDimensions.event_type in ("INJECTION_BLOCKED", "CREDENTIAL_DETECTED")
| summarize count() by tostring(customDimensions.event_type), bin(timestamp, 5m)
```

### Log format

```json
{
  "event": "mcp_tool_call",
  "tool": "get_holdings",
  "user_id": "alice@contoso.com",
  "outcome": "success",
  "duration_ms": 12.3
}
```

Security events from `log_security_event()` use a separate schema:

```json
{
  "event_type": "INJECTION_BLOCKED",
  "category": "shell_injection",
  "correlation_id": "<uuid>",
  "severity": "WARNING",
  "injection_type": "shell_injection",
  "description": "shell metacharacter"
}
```

| Field | Values | Notes |
|---|---|---|
| `event` | `"mcp_tool_call"` | Fixed — lets you filter MCP events from other log noise |
| `tool` | tool function name | e.g. `"get_holdings"`, `"get_quote"` |
| `user_id` / `caller_id` | oid, sub, or email | `user_id` in portfolio-db; `caller_id` in yahoo-finance |
| `outcome` | `"success"` / `"error"` / `"denied"` | `"denied"` = scope check or content safety rejection |
| `duration_ms` | float | Wall-clock ms from scope check to return / exception |
| `error` | exception message | Present only when outcome is not `"success"` |

### Tool instrumentation pattern

```python
# mcp-servers/portfolio-db/server.py  (same pattern in yahoo-finance)

@mcp.tool()
def get_holdings() -> dict:
    user_id = _get_user_id_from_context()
    _t0 = time.monotonic()
    _outcome = "error"
    _err: str | None = None
    try:
        check_scope("portfolio.read")
        portfolio = _get_portfolio(user_id)
        _outcome = "success"
        return {"user_id": user_id, ...}
    except PermissionError as exc:
        _outcome = "denied"
        _err = str(exc)
        raise
    except Exception as exc:
        _err = str(exc)
        raise
    finally:
        audit_log("get_holdings", user_id, _outcome,
                  (time.monotonic() - _t0) * 1000, _err)
```

Key design decisions:
- `user_id` is resolved *before* the try block so it is always available in `finally`,
  even if `check_scope` raises.
- `_outcome` defaults to `"error"`; it is set to `"success"` only at the last return, so
  if a new code path is added without updating `_outcome` it will log conservatively.
- `PermissionError` and `ValueError` (from `check_scope` / `_validate_symbol` /
  `check_content_safety`) are caught separately and marked `"denied"`.

### Routing to Azure Monitor

Container Apps write stdout to Log Analytics automatically.  Query in Azure Monitor:

```kusto
ContainerAppConsoleLogs_CL
| where ContainerName_s in ("portfolio-db-mcp", "yahoo-finance-mcp")
| where Log_s contains "mcp_tool_call"
| extend entry = parse_json(Log_s)
| project TimeGenerated,
          tool      = entry.tool,
          user_id   = entry.user_id,
          outcome   = entry.outcome,
          duration  = entry.duration_ms,
          error     = entry.error
| order by TimeGenerated desc
```

---

## 11. Prompt Injection Defense — Azure AI Content Safety (MCP06)

The MCP tool functions accept string arguments supplied by an LLM.  A compromised or
manipulated LLM could be induced to pass adversarial strings — such as embedded
instructions — as tool arguments.  Azure AI Content Safety provides a semantic layer
that detects such patterns before the argument reaches business logic.

### How it works

`check_content_safety(text)` in `entra_auth.py` is called on **every string argument**
in every tool, *before* regex/whitelist validation:

```python
# mcp-servers/yahoo-finance/server.py

@mcp.tool()
def get_quote(symbol: str) -> dict:
    ...
    check_content_safety(symbol)   # semantic check  <-- NEW
    symbol = _validate_symbol(symbol)   # format check
    ...
```

The function:
1. Resolves a module-level `ContentSafetyClient` on first call (lazy init, then cached).
2. Calls `analyze_text()` from the `azure-ai-contentsafety` SDK.
3. Raises `ValueError` if any category (Hate, SelfHarm, Sexual, Violence) is at
   severity >= 4 (medium).
4. **No-ops silently** if `AZURE_CONTENT_SAFETY_ENDPOINT` is not set — safe in dev.
5. **Logs but does not block** on Content Safety API errors — availability of the safety
   service is not a hard dependency.

### Defense-in-depth layering (Camp 3 I/O Security — three-layer input + output pipeline)

```
LLM argument
    |
    v (1) check_injection_patterns()  — technical: shell/SQL/path traversal/template regex (MCP-05)
    |
    v (2) check_prompt_shields()      — AI: Azure Content Safety Prompt Shields jailbreak detection (MCP-06)
    |
    v (3) check_content_safety()      — semantic: hate/violence/self-harm/sexual categories
    |
    v (4) _validate_symbol()          — format: regex [A-Z0-9.\-\^=]{1,10}
    |
    v (5) parameterised SQL / yfinance — structural: no string interpolation
    |
    v (6) row-level security          — data: user_id == OBO identity
    |
    v (7) scan_output_credentials()   — output: credential redaction + entropy analysis (MCP-10)
                                        (applied to get_news and any tool returning third-party content)
```

Even if Content Safety is disabled or skipped, layers 1, 4–6 provide robust protection
against injection for the current tool argument types.  Layer 7 protects against accidental
secret exfiltration in tool responses.

### Provisioning Content Safety

```bicep
// Add to infra/modules/ — example resource
resource contentSafety 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' = {
  name: '${prefix}-content-safety'
  location: location
  kind: 'ContentSafety'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
}
```

Set `AZURE_CONTENT_SAFETY_ENDPOINT` on each MCP Container App to
`contentSafety.properties.endpoint`.  Both MCP servers use `DefaultAzureCredential` which
resolves the Container App's managed identity automatically.

---

## 12. Supply Chain Security — Dependabot (MCP03/MCP04)

`.github/dependabot.yml` configures weekly automated pull requests for all dependency
manifests in the repository:

| Ecosystem | Directory | Labels |
|---|---|---|
| `pip` | `/backend` | `dependencies`, `backend` |
| `pip` | `/mcp-servers/portfolio-db` | `dependencies`, `mcp-portfolio` |
| `pip` | `/mcp-servers/yahoo-finance` | `dependencies`, `mcp-yahoo` |
| `pip` | `/a2a-agents/esg-advisor` | `dependencies`, `a2a-esg` |
| `npm` | `/frontend` | `dependencies`, `frontend` |
| `github-actions` | `/` | `dependencies`, `github-actions` |

### Grouping strategy

Related packages are grouped into single PRs to reduce noise:

- `azure-*` packages in backend and MCP servers → one PR per service
- React packages (react, react-*, @types/react*) → one PR
- Vite packages (vite, @vitejs/*) → one PR
- Tailwind packages → one PR

### Enabling GitHub Advanced Security alerts

For supply chain *vulnerability* alerts (not just version bumps), enable in
**Settings → Code security and analysis**:

- **Dependency graph** — required for Dependabot
- **Dependabot alerts** — notifies on known CVEs
- **Dependabot security updates** — auto-opens security PRs (independent of schedule)

---

## 13. Cross-IDP Single Sign-On — Okta + Entra + MCP

This section documents all four solutions to the double-authentication problem that
occurs when Copilot Studio (Okta IDP) calls an MCP server secured with Entra.

### The core problem

```
Copilot Studio (authenticated with Okta)
    --> APIM
        --> MCP Server on ACA (expects Entra JWT)
                                ^--- Entra auth prompt appears here
```

The MCP server's `EntraTokenVerifier` validates against Entra's JWKS.  An Okta JWT
never passes that check, so Entra re-prompts the user — even though they already
authenticated with Okta.

**Root cause:** Token audiences are IdP-scoped.  An Okta token's `aud` will never equal
`api://<Entra-MCP-ClientID>`.  The two identity systems are isolated.

**Key constraint:** Entra's OBO grant (`urn:ietf:params:oauth:grant-type:jwt-bearer`)
only accepts **Entra-issued** JWTs as the `assertion` parameter.  Feeding an Okta token
into the OBO endpoint returns a 400.  There is no native Entra call that converts an
Okta token into a delegated Entra token — short of federation (Option D).

---

### Option A — APIM Token Exchange Policy (no code changes)

**Best for:** Fastest path to production with no Okta-side configuration required.

```
Copilot Studio (Okta JWT)
    |
    v
APIM (inbound policy):
    1. validate-jwt against Okta JWKS        <- validates user is legit
    2. extract sub/email from Okta token     <- capture user identity
    3. authentication-managed-identity       <- APIM MI gets Entra service token
       resource = api://<MCP_CLIENT_ID>
    4. replace Authorization: Bearer <Entra service token>
    5. inject X-Forwarded-User: <okta-email>
    |
    v
MCP Server (ACA, internal ingress):
    - EntraTokenVerifier validates Entra MI token (passes)
    - X-Forwarded-User read by get_user_id_from_request() for RLS
    - No user interaction required
```

**APIM inbound policy:**

```xml
<inbound>
    <!-- Step 1: Validate incoming Okta token -->
    <validate-jwt header-name="Authorization" failed-validation-httpcode="401"
                  failed-validation-error-variable-name="jwt-error">
        <openid-config url="https://<okta-domain>/oauth2/default/.well-known/openid-configuration" />
        <audiences>
            <audience>api://<okta-app-client-id></audience>
        </audiences>
    </validate-jwt>

    <!-- Step 2: Extract user identity from validated token -->
    <set-variable name="okta-user"
        value="@(context.Request.Headers.GetValueOrDefault("Authorization","")
                  .AsJwt()?.Claims.GetValueOrDefault("email",
                    context.Request.Headers.GetValueOrDefault("Authorization","")
                      .AsJwt()?.Claims.GetValueOrDefault("sub","unknown")))" />

    <!-- Step 3 + 4: Swap Authorization header — APIM MI token for MCP app reg -->
    <authentication-managed-identity resource="api://<MCP_CLIENT_ID>"
                                     output-token-variable-name="mcp-token"
                                     ignore-error="false" />
    <set-header name="Authorization" exists-action="override">
        <value>@("Bearer " + (string)context.Variables["mcp-token"])</value>
    </set-header>

    <!-- Step 5: Forward user identity as a trusted header -->
    <set-header name="X-Forwarded-User" exists-action="override">
        <value>@((string)context.Variables["okta-user"])</value>
    </set-header>
</inbound>
```

**Why X-Forwarded-User is safe here:**
The MCP server Container App has `external: false` (internal ingress only).  The only
path to that server is through APIM.  `X-Forwarded-User` cannot be spoofed by an
external caller because there is no external route.

**MCP server changes needed:** None.  `get_user_id_from_request()` in `entra_auth.py`
already falls back to the `X-User-Id` / `X-Forwarded-User` header when the `oid` claim
is absent from a service token.

**Azure prerequisites:**
- APIM instance (already in the customer architecture)
- APIM's Managed Identity must have the `<MCP_CLIENT_ID>` API permission granted via
  Entra app role or scope assignment
- APIM must be able to reach the internal ACA ingress (VNet peering or Container Apps
  Environment with APIM in the same VNet)

**Tradeoffs:**
| | |
|---|---|
| User identity | In `X-Forwarded-User` header (trusted but unsigned) |
| Okta changes | None |
| Code changes | None |
| New infrastructure | APIM policy + MI permission |
| Time to ship | 1-2 days |

---

### Option B — Multi-IDP Trust on MCP Server (already implemented)

**Best for:** Cryptographically-signed user identity end-to-end, if Okta authorization
server configuration is possible.

**This is already implemented in this codebase.**  `MultiIDPTokenVerifier` in
`mcp-servers/portfolio-db/entra_auth.py` and `mcp-servers/yahoo-finance/entra_auth.py`
accepts tokens from any OIDC-compliant issuer listed in `TRUSTED_ISSUERS`.

```
Copilot Studio (Okta JWT, aud=api://<MCP_CLIENT_ID>)
    |
    v
APIM (pass-through — no token modification needed)
    |
    v
MCP Server:
    MultiIDPTokenVerifier.verify_token(token):
        1. Read 'iss' from unverified claims
        2. Compare against [entra_issuer] + TRUSTED_ISSUERS
        3. Fetch JWKS from issuer's /.well-known/openid-configuration
        4. Validate RS256 signature, audience, expiry
        5. Return AccessToken with claims (sub, email, scp)
    RLS uses claims["email"] or claims["sub"] directly — no header needed
```

**Required Okta configuration:**

The Okta Authorization Server must issue tokens with:
- `aud` = `api://<MCP_CLIENT_ID>` (the Entra app registration client ID of the MCP server)
- `scp` or `scope` containing the required scopes (e.g. `portfolio.read`)

In Okta Admin Console:
1. **Security → API → Authorization Servers** → select your server
2. **Scopes** → add `portfolio.read`, `market.read`
3. **Access Policies** → allow the Copilot Studio app to request those scopes
4. **Token** tab → set **Audience** to `api://<MCP_CLIENT_ID>`

**Activation (one env var change per MCP server):**

```bash
# mcp-servers/portfolio-db/.env  or ACA environment variable
TRUSTED_ISSUERS=https://dev-xxxxx.okta.com/oauth2/default

# mcp-servers/yahoo-finance/.env
TRUSTED_ISSUERS=https://dev-xxxxx.okta.com/oauth2/default
```

Both servers are already using `MultiIDPTokenVerifier()` as their auth provider.
Setting `TRUSTED_ISSUERS` activates the multi-IDP path automatically.

**Local simulation (no real Okta needed):**

```bash
# Terminal 1 — start mock OIDC server (simulates Okta)
6_run_mock_oidc.bat

# Terminal 2 — start yahoo-finance MCP with mock OIDC trusted
# Edit mcp-servers/yahoo-finance/.env:
#   TRUSTED_ISSUERS=http://localhost:8888
#   MCP_CLIENT_ID=mock-mcp-client
3_run_mcp_yahoo.bat

# Obtain a mock Okta token
curl http://localhost:8888/token/for/alice@demo.com?audience=api://mock-mcp-client

# Call MCP tool with that token
curl -H "Authorization: Bearer <token>" http://localhost:8001/mcp/tools/list
```

**Tradeoffs:**
| | |
|---|---|
| User identity | JWT claim (cryptographically signed, no header trust required) |
| Okta changes | Must configure audience = api://<MCP_CLIENT_ID> |
| Code changes | None (already in codebase) |
| New infrastructure | None |
| Time to ship | Hours (if Okta audience can be configured) |

---

### Option C — Okta-to-Entra Token Exchange Proxy (implemented in this repo)

**Best for:** Demo/showcase when neither Okta audience configuration nor Entra
federation is available, or when centralized mapping + audit logging is required.

```
Copilot Studio (Okta JWT)
    |
    v
okta-proxy (mcp-servers/okta-proxy/server.py, port 8003):
    1. Validate Okta JWT via JWKS           <- ensures user is authenticated
    2. Extract sub/email claim              <- user identity
    3. Apply USER_MAPPING dict              <- Okta email -> Entra UPN
    4a. Dev mode:  use TARGET_MCP_TOKEN     <- static dev token
    4b. Prod mode: client_credentials       <- Entra service token for MCP app reg
    5. Add X-Forwarded-User: <mapped-email>
    6. Proxy full request (incl. SSE)
    |
    v
MCP Server:
    - Validates Entra/dev token
    - Reads X-Forwarded-User for RLS
```

**Why this is NOT true OBO:**
Entra's OBO grant requires an Entra-issued `assertion`.  The proxy uses
`client_credentials` instead, producing a service token.  User identity travels in
`X-Forwarded-User` (same trust model as APIM Option A).  This is semantically equivalent
to Option A but implemented as a Python service rather than an APIM policy.

**Running locally:**

```bash
# 1. Start mock OIDC (simulates Okta)
6_run_mock_oidc.bat

# 2. Start the target MCP server (yahoo-finance on :8001)
3_run_mcp_yahoo.bat

# 3. Start the proxy
7_run_okta_proxy.bat

# 4. Get a mock Okta token
curl http://localhost:8888/token/for/alice@demo.com?audience=api://mock-mcp-client

# 5. Call the proxy — no Entra login, no popup
curl -H "Authorization: Bearer <okta-token>" http://localhost:8003/mcp/tools/list
```

**Key proxy configuration (mcp-servers/okta-proxy/.env):**

```ini
OKTA_ISSUER=http://localhost:8888          # or real Okta issuer URL
OKTA_AUDIENCE=api://mock-mcp-client        # must match token 'aud' claim
TARGET_MCP_URL=http://localhost:8001       # downstream MCP server
TARGET_MCP_TOKEN=dev-yahoo-mcp-token       # dev mode only

# Optional user mapping (JSON)
USER_MAPPING={"alice@okta.example":"alice@company.onmicrosoft.com"}

# Production Entra values (leave blank for dev mode)
ENTRA_TENANT_ID=
ENTRA_CLIENT_ID=
ENTRA_CLIENT_SECRET=
MCP_CLIENT_ID=
```

**Tradeoffs:**
| | |
|---|---|
| User identity | Header (trusted, not signed — same as Option A) |
| Okta changes | None |
| Code changes | New service (already built in this repo) |
| New infrastructure | One extra Container App in ACA |
| Time to ship | 1 week |

---

### Option D — Entra External Identities Federation with Okta (strategic)

**Best for:** Long-term production architecture.  Zero code changes.  Full
cryptographic user identity propagation with no proxy layer.

```
Okta user authenticates
    |
    v
Entra External Identities (B2B federation):
    - Okta is configured as a SAML/OIDC identity provider in the Entra tenant
    - Okta users appear as guest/member accounts in Entra
    - SCIM provisioning synchronises users from Okta to Entra
    |
    v
Copilot Studio (obtains an Entra token via the federated identity)
    |  Bearer <Entra token>  (aud = backend or MCP app reg)
    v
APIM -> MCP Server:
    - Existing EntraTokenVerifier works unchanged
    - Existing OBO flow works unchanged
    - Full oid claim present — RLS, audit logging, scope enforcement all work
    - NO proxy layers, NO X-Forwarded-User headers
```

**Setup steps (Entra + Okta admin coordination required):**

**Step 1 — Configure Okta as a federated IdP in Entra:**
1. Entra Admin Center → **External Identities → All identity providers**
2. Add a new **OIDC** provider:
   - Display name: `Okta`
   - Client ID: Okta app client ID
   - Client secret: Okta app client secret
   - Issuer URL: `https://<okta-domain>/oauth2/default`
   - Scopes: `openid profile email`
3. Under **Cross-tenant access settings** → configure inbound trust for Okta users

**Step 2 — Provision users via SCIM:**

Okta has a built-in **Microsoft Entra ID** app in Okta Integration Network:
1. In Okta Admin: **Applications → Browse App Catalog** → "Microsoft Entra ID"
2. Configure SCIM provisioning to create/update guest accounts in Entra
3. Map Okta profile attributes to Entra attributes (especially `mail` → `userPrincipalName`)

**Step 3 — Update Copilot Studio authentication:**
- Configure Copilot Studio to use **Entra** (not Okta) as the auth provider, but
  federated login routes through Okta transparently for Okta users
- Or use Entra's **Sign in with external IdP** flow directly in Copilot Studio

**Step 4 — No MCP server changes:**
The existing `EntraTokenVerifier` and OBO flow handle everything.  The Okta user is
now a first-class Entra identity.

**Tradeoffs:**
| | |
|---|---|
| User identity | JWT claim, cryptographically signed end-to-end |
| Okta changes | Create OIDC app, configure SCIM |
| Entra changes | Configure external IdP, inbound trust, SCIM |
| Code changes | None |
| New infrastructure | None |
| Time to ship | Weeks (admin coordination + user provisioning testing) |

---

### Comparison summary

| | Option A: APIM Policy | Option B: Multi-IDP | Option C: Proxy | Option D: Federation |
|---|---|---|---|---|
| User identity in MCP | Header (trusted) | JWT claim (signed) | Header (trusted) | JWT claim (signed) |
| Okta admin needed | No | Yes (audience config) | No | Yes (OIDC + SCIM) |
| Entra admin needed | MI permissions | No | No (dev) / Yes (prod) | Yes (external IdP) |
| Code changes | None | None | New service | None |
| Simulated in this repo | No (APIM required) | Yes — `6_run_mock_oidc.bat` | Yes — `7_run_okta_proxy.bat` | No |
| Production-ready | Yes | Yes | Yes (with Entra creds) | Yes (after setup) |
| Recommended phase | Fastest path | If Okta audience configurable | Demo / audit logging | Long-term target |
