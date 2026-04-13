# Portfolio Advisor — Example Prompts Deep Dive

> **Scope:** End-to-end technical breakdown of every example prompt group shown in the UI,
> covering data flow, authentication, MCP patterns, architectural best practices, production
> hardening recommendations, and a balanced pros/cons evaluation.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Economic Data](#2-economic-data)
3. [Market Intelligence](#3-market-intelligence)
4. [Portfolio Data](#4-portfolio-data)
5. [Real-time Quotes](#5-real-time-quotes)
6. [GitHub Intelligence](#6-github-intelligence)
7. [Handoff Routing](#7-handoff-routing)
8. [ESG Advisor](#8-esg-advisor)
9. [Concurrent Analysis](#9-concurrent-analysis)
10. [Cross-Cutting: MCP Pattern Reference](#10-cross-cutting-mcp-pattern-reference)
11. [Cross-Cutting: AuthN and AuthZ Best Practices Applied](#11-cross-cutting-authn-and-authz-best-practices-applied)
12. [Production Hardening Recommendations](#12-production-hardening-recommendations)
13. [Architectural Pros and Cons](#13-architectural-pros-and-cons)

---

## 1. System Overview

```
Browser (React SPA + MSAL)
        |  Bearer <Entra access token>  (aud = backend API app reg)
        v
FastAPI Backend  (uvicorn, Python 3.11)
        |
        |-- Validates JWT via JWKS ...................... core/auth/middleware.py
        |-- Extracts AuthContext (claims + raw token) ... core/auth/middleware.py
        |-- Input guardrails ............................ core/guardrails/policy.py
        |-- Routes to PortfolioOrchestrator ............. routes/chat.py
        |
        |   HandoffBuilder (single specialist, routed by triage agent)
        |   ConcurrentBuilder (all specialists run in parallel)
        |
        +-- Pattern 1a: Private MCP (OBO) -------> portfolio-db MCP  (internal)
        |                                       --> yahoo-finance MCP (internal)
        |
        +-- Pattern 1b: External Public MCP -----> Alpha Vantage MCP (remote SaaS)
        |                (backend API key)
        |
        +-- Pattern 2: External Vendor MCP ------> GitHub MCP (api.githubcopilot.com)
        |                (per-user OAuth token)
        |
        +-- A2A: Remote LangChain Agent ---------> ESG Advisor A2A server
        |
        +-- Foundry Prompt Agent (Bing) ---------> Market Intelligence (Bing Grounding)
```

### Component Roles

| Component | Technology | Purpose |
|---|---|---|
| Frontend | React + MSAL + TypeScript | SPA, SSE streaming, prompt library |
| Backend API | FastAPI + Python asyncio | Orchestration, auth, guardrails, SSE |
| Triage Agent | Azure AI Foundry LLM | Intent detection, routing decisions |
| Portfolio DB MCP | FastMCP + SQLite/Fabric | Confidential portfolio RLS data |
| Yahoo Finance MCP | FastMCP + yfinance | Public market data, fundamentals |
| Alpha Vantage MCP | Remote hosted SaaS | Macro economic indicators |
| GitHub MCP | GitHub-hosted endpoint | Engineering activity, repo metrics |
| ESG Advisor | LangChain ReAct + A2A | Governance risk, ESG scoring |
| Market Intel Agent | Foundry Prompt Agent + Bing | Web-grounded market news |
| Azure Cosmos DB | NoSQL multi-container | Session history, vendor tokens, checkpoints |
| Azure AI Search | Cognitive Search | RAG for research documents (triage context) |
| Azure AI Foundry | Agent Framework + LLM | Model hosting, agent lifecycle |
| Azure Monitor / OTel | Application Insights | Distributed tracing, audit logs |

---

## 2. Economic Data

**Sample prompts:**
- "What is the current Fed funds rate and 10-year treasury yield?"
- "Show CPI and inflation trend over the last 12 months"
- "What does the yield curve shape signal for recession risk?"

### 2.1 End-to-End Data Flow

```
1. User submits prompt in ChatPanel
2. Frontend: POST /api/chat/message  { message, session_id, mode: "handoff" }
             Authorization: Bearer <Entra token>   (or no token — requiresAuth: false)
3. Backend: require_auth_context validates token (or returns dev identity)
4. Guardrail: check_user_message(message) — content policy check
5. PortfolioOrchestrator.run_handoff()
6. HandoffBuilder: triage_agent evaluates user message
   - triage matches: "Economic data, interest rates, Fed policy..." → routes to economic_agent
7. EconomicDataAgent activated; its FunctionTools (or MCPStreamableHTTPTool) are called:
   a. FunctionTool path (no alphavantage_api_key):
      - Python closures call Alpha Vantage REST API directly
        GET https://www.alphavantage.co/query?function=FEDERAL_FUNDS_RATE&apikey=<key>
      - Response trimmed to INTERVAL_MAX_POINTS before returning to LLM
   b. Remote MCP path (alphavantage_api_key set):
      - MCPStreamableHTTPTool connects to https://mcp.alphavantage.co/mcp?apikey=<key>
      - Tools discovered via MCP capability negotiation
      - LLM calls tools like get_federal_funds_rate, get_treasury_yield, get_cpi
8. LLM synthesizes economic analysis with observation dates
9. SSE stream: agent_response chunks streamed to browser
10. CosmosDB: message persisted under session_id / user_id
```

### 2.2 End-to-End Authentication Flow

```
Browser -- no Entra token required for public economic data -->
                      |
              Backend auth middleware
              (dev identity returned if no token)
                      |
              EconomicDataAgent.build_tools()
                      |
              Pattern 1b: Backend API Key
              ALPHAVANTAGE_API_KEY (from Key Vault / env var)
              injected as URL param: ?apikey=<key>
                      |
              Alpha Vantage SaaS
              (no user identity — public data)
```

- No Entra token is required by Alpha Vantage.
- The API key is a **backend secret** held in Key Vault, injected via env var.
- The key is never exposed to the browser, never logged, never included in any response.

### 2.3 MCP Pattern — Pattern 1b (External Public MCP with Backend API Key)

**Implementation:** `backend/app/agents/economic_data.py`

| Property | Value |
|---|---|
| MCP host | Remote SaaS (https://mcp.alphavantage.co) |
| Transport | Streamable HTTP (MCP 2025-11-25 spec) |
| Auth mechanism | API key in URL query param |
| User identity propagated? | No — public economic data |
| RLS? | No |
| Data classification | PUBLIC |
| Fallback | Direct REST FunctionTools when API key absent |

**Key design choice — FunctionTool fallback:** If `ALPHAVANTAGE_API_KEY` is not set,
`_build_av_tools()` creates Python async functions wrapped as `FunctionTool` instances
that call the Alpha Vantage REST API directly. This allows local development without
needing the remote MCP endpoint while keeping the same agent interface.

**Context window management:** Alpha Vantage returns time series data newest-first.
The `INTERVAL_MAX_POINTS` dictionary caps the number of data points returned per
interval type (e.g. 30 daily, 24 monthly) before handing data to the LLM. This
prevents context window exhaustion on high-frequency series.

### 2.4 Architectural Best Practices Applied

- **Secret isolation:** API key never leaves the backend process; stored in Key Vault.
- **Context budget control:** `INTERVAL_MAX_POINTS` prevents unbounded data injection.
- **Graceful degradation:** FunctionTool fallback ensures agent functions without remote MCP.
- **Single responsibility:** The economic agent only handles public macro data, not positions.
- **Observation date citations:** System prompt mandates citing observation dates to prevent stale data misrepresentation.

---

## 3. Market Intelligence

**Sample prompts:**
- "What are the latest analyst upgrades or downgrades for NVDA?"
- "Summarize today's market-moving news for the tech sector"
- "What geopolitical risks are currently affecting energy stocks?"

### 3.1 End-to-End Data Flow

```
1. User submits prompt → POST /api/chat/message
2. Triage agent routes to market_intel_agent
   (matches: "Market news, stock analysis, earnings, sector trends...")
3. MarketIntelAgent.create() instantiates a Foundry Prompt Agent:
   - Connects to pre-configured "portfolio-market-intel" agent in Azure AI Foundry
   - Uses RawFoundryAgentChatClient (not the shared FoundryChatClient)
4. The Foundry Prompt Agent has Bing Grounding configured server-side
   - Bing Search connection attached to the Foundry project
   - Agent performs live web searches for current market data
5. LLM returns cited market analysis with source name, date, key quote
6. SSE stream: agent_response chunks → browser
```

### 3.2 End-to-End Authentication Flow

```
Browser Bearer token (optional for this agent)
                 |
         Backend require_auth_context
                 |
         MarketIntelAgent.create()
                 |
         RawFoundryAgentChatClient (project_endpoint, agent_name)
                 |
         Azure AI Foundry Agents Service
         - Managed Identity authenticates backend → Foundry
         - Bing Grounding uses Foundry project Managed Identity
           (no API key needed; Bing connection managed by Foundry)
                 |
         Bing Search API (via Foundry-managed connection)
```

- The backend uses `DefaultAzureCredential` → Managed Identity to authenticate with Foundry.
- Bing Grounding is a **hosted tool** — it must be defined on the server-side agent, not passed at call time.
- No user token is forwarded to Bing; this agent returns only public market information.

### 3.3 MCP Pattern — Foundry Prompt Agent with Bing Grounding

This agent does not use the MCP protocol directly. Instead it demonstrates a Foundry
**Prompt Agent** pattern:

| Property | Value |
|---|---|
| Agent type | Foundry-hosted Prompt Agent |
| Grounding | Bing Search (Foundry-managed connection) |
| Auth to Foundry | Managed Identity (no client secret) |
| User identity propagated? | No — public news data |
| Data classification | PUBLIC |

**Why `RawFoundryAgentChatClient` instead of `FoundryChatClient`?**

The shared `FoundryChatClient` is used for most agents because it supports tool injection
at call time. `RawFoundryAgentChatClient` wraps a pre-configured Foundry agent definition
and calls it as-is. The Market Intel agent's Bing Grounding is a server-side capability
that cannot be injected at request time — hence the `RawFoundryAgentChatClient` pattern.

### 3.4 Architectural Best Practices Applied

- **Managed Identity for Bing:** No API key management required; Foundry project connection abstracts credentials.
- **Server-side tool definition:** Bing Grounding configured in Foundry portal, not in code — decouples infrastructure from application code.
- **Cited sources mandate:** System prompt requires source name, publication date, key quote — reduces hallucination risk for time-sensitive data.
- **Clear data boundaries:** System prompt explicitly prohibits access to portfolio positions.
- **RAG + Grounding:** Agents Service retrieves both structured search results (AI Search, via triage context) and live web data (Bing), combining RAG and real-time grounding.

---

## 4. Portfolio Data

**Sample prompts:**
- "Show my current holdings, sector weights, and cash position"
- "What is my portfolio Sharpe ratio and max drawdown this year?"
- "Which positions have the highest concentration risk?"

### 4.1 End-to-End Data Flow

```
1. User must be authenticated (requiresAuth: true)
2. POST /api/chat/message with Entra Bearer token
3. require_auth_context validates RS256 JWT via Entra JWKS
   - Extracts AuthContext { claims, raw_token }
   - user_id = preferred_username (email) or oid
4. Triage agent routes to portfolio_agent
5. PortfolioDataAgent.build_tools() called with raw_token
6. build_obo_http_client():
   - Detects production mode (ENTRA_TENANT_ID + client_secret set)
   - Creates OBOAuth httpx auth handler
7. MCPStreamableHTTPTool connects to http://portfolio-db-mcp/mcp
   - Authorization: Bearer <OBO token>  (aud = api://<portfolio_mcp_client_id>)
8. Portfolio MCP server:
   - EntraTokenVerifier.verify_token(): JWKS validation, audience, issuer, expiry
   - check_scope("portfolio.read")
   - get_user_id_from_request() → extracts oid / preferred_username from OBO claims
   - SQL query: SELECT * FROM holdings WHERE user_id = ?  ← strict RLS
9. Holdings data returned → LLM computes weights, risk metrics, allocations
10. Response streamed via SSE
11. Message persisted to CosmosDB (session_id + user_id partition)
```

### 4.2 End-to-End Authentication Flow

```
Browser
  MSAL acquireTokenSilent()
  Bearer <Entra token A>  (aud = backend API app reg)
         |
  FastAPI middleware
  EntraJWTValidator.validate(token)
    - GET JWKS from Entra (cached by kid)
    - RS256 verify (aud, iss, exp, nbf)
  AuthContext { claims, raw_token: tokenA }
         |
  OBOAuth.async_auth_flow()
  OnBehalfOfCredential(
    tenant_id, client_id=backend_app,
    client_secret=<Key Vault>,
    user_assertion=tokenA
  )
  POST login.microsoftonline.com/.../token
    grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer
    requested_token_use=on_behalf_of
    scope=api://<portfolio_mcp_client_id>/portfolio.read
  --> Bearer <OBO token B>  (aud = portfolio MCP, oid preserved)
         |
  Portfolio MCP Server
  EntraTokenVerifier: JWKS validate OBO token B
  check_scope("portfolio.read")
  oid claim → WHERE user_id = oid  (row-level security)
```

**Token lineage:**
- Token A: `aud=backend_client_id`, `scp=chat.access`
- Token B (OBO): `aud=api://portfolio_mcp_client_id`, `scp=portfolio.read`, `oid=<same user>`

The OBO exchange preserves the user's `oid` across the trust boundary. The MCP server
sees the real user identity without the backend ever needing to set a trusted header.

### 4.3 MCP Pattern — Pattern 1a (Private MCP with OBO)

| Property | Value |
|---|---|
| MCP host | Internal Azure Container App (external: false) |
| Transport | Streamable HTTP (MCP 2025-11-25) |
| Auth mechanism | Entra OBO JWT (RS256 JWKS) |
| Scope | `api://<portfolio_mcp_client_id>/portfolio.read` |
| User identity propagated? | Yes — via OBO token oid claim |
| RLS | SQL WHERE user_id = oid on every query |
| Data classification | CONFIDENTIAL |

### 4.4 Architectural Best Practices Applied

- **Zero-trust between backend and MCP:** No implicit ambient trust; every call requires a valid OBO token.
- **Audience isolation:** OBO token's audience is `api://portfolio_mcp_client_id`, accepted by no other service.
- **Scope minimization:** `portfolio.read` scope; no write permissions exposed via MCP.
- **Internal ingress only:** Container App `external: false` — unreachable from public internet; only accessible via Container Apps environment's internal VNet.
- **Per-request token validation:** FastMCP's `auth=EntraTokenVerifier()` validates every inbound request.
- **No token passthrough:** The user's original token is never forwarded; it is exchanged for a new audience-scoped token.
- **RLS at data layer:** Even if the application layer were compromised, the SQL filter by `oid` prevents cross-user data exposure.
- **Cosmos session isolation:** Sessions partitioned by `user_id` — Cosmos point reads via partition key enforce logical data isolation.

---

## 5. Real-time Quotes

**Sample prompts:**
- "Get AAPL current P/E and EV/EBITDA vs sector median"
- "Show MSFT analyst price targets and recommendation breakdown"
- "What are the 52-week range and moving averages for TSLA?"

### 5.1 End-to-End Data Flow

```
1. POST /api/chat/message (auth optional — public market data)
2. Triage agent routes to private_data_agent
   (matches: "Real-time quotes, company financials, valuation multiples...")
3. PrivateDataAgent.build_tools() called with raw_token
4. build_obo_http_client() creates OBO-authenticated httpx.AsyncClient
5. MCPStreamableHTTPTool connects to http://yahoo-finance-mcp/mcp
   - Authorization: Bearer <OBO token>  (scope: api://<yahoo_mcp_client_id>/market.read)
6. Yahoo Finance MCP server:
   - EntraTokenVerifier validates OBO token
   - check_scope("market.read")
   - audit_log() records caller_id and tool name with latency
   - yf.Ticker(symbol).fast_info / .info → real-time or delayed quote data
7. LLM formats fundamentals, valuation multiples, analyst consensus
8. SSE stream → browser
```

### 5.2 End-to-End Authentication Flow

Same OBO pattern as Portfolio Data (Pattern 1a), but scope is `market.read` and the
MCP target is the Yahoo Finance app registration.

```
Entra token (aud=backend) → OBO exchange → OBO token (aud=yahoo_mcp_client_id)
→ Yahoo Finance MCP validates JWKS → check_scope("market.read") → yfinance call
```

**Note:** Yahoo Finance serves public market data, so there is no per-user RLS.
The OBO token still enforces that only authorized backends can invoke the MCP and
provides a complete audit trail tying each tool call to a specific user's `oid`.

### 5.3 MCP Pattern — Pattern 1a (Private MCP with OBO)

| Property | Value |
|---|---|
| MCP host | Internal Container App |
| Auth mechanism | Entra OBO JWT, scope: `market.read` |
| User identity propagated? | Yes (for audit trail) |
| RLS | No (public market data) |
| Input validation | `_validate_symbol()` — regex `^[A-Z0-9.\-\^=]{1,10}$` |
| Audit logging | `audit_log()` on every tool call with latency, caller_id, outcome |
| Data classification | PUBLIC (market data) |

### 5.4 Architectural Best Practices Applied

- **Input validation at MCP boundary:** `_validate_symbol()` enforces an allowlist regex on all ticker symbols before any yfinance call, preventing injection attacks.
- **Audit logging per tool call:** `audit_log()` records `caller_id`, `tool`, `duration_ms`, `outcome` ("success" / "error") to structured logs — feeds into Application Insights.
- **LRU caching for expensive data:** `@lru_cache` on certain yfinance calls avoids redundant HTTP requests within the same process lifetime.
- **Defensive data extraction:** All yfinance fields extracted with `.get(key, 0)` or `.get(key, None)` fallbacks — the yfinance library can return incomplete data for some tickers without raising exceptions.
- **Scope layering:** Even though market data is public, the OBO scope requirement ensures the route from browser to data cannot be bypassed (e.g. by calling the MCP directly from an unauthorized backend).

---

## 6. GitHub Intelligence

**Sample prompts:**
- "How active is Microsoft's engineering on GitHub? Analyze MSFT commit velocity"
- "Compare open-source health of Meta vs Google — which shows stronger dev momentum?"
- "What is the release cadence and issue backlog for NVIDIA's CUDA repos?"

### 6.1 End-to-End Data Flow

```
Connect flow (one-time, per user):
1. User clicks "Connect GitHub" in NavBar
2. GET /api/auth/github  (with Entra Bearer)
3. Backend: extract user_oid from Entra token
4. Build HMAC-signed state = {oid, timestamp}
5. 302 Redirect → https://github.com/login/oauth/authorize
                    ?client_id=<github_oauth_app>
                    &scope=public_repo,read:user
                    &state=<hmac_state>
6. User authorizes in GitHub UI
7. GitHub redirects to GET /api/auth/github/callback?code=<code>&state=<hmac_state>
8. Backend: _verify_state() — HMAC check + 10-min timestamp window
9. POST github.com/login/oauth/access_token  → { access_token, scope }
10. GitHubTokenStore.store_token(user_oid, access_token) → Cosmos DB
11. Redirect 302 → <frontend>?github_connected=true

Chat flow (per message):
1. PortfolioOrchestrator.run_handoff() called
2. _fetch_github_token(user_oid):
   - Reads from Cosmos DB: vendor-oauth-tokens / partition user_oid / id "<oid>-github"
   - Returns token or None
3. self._github_token set on orchestrator (sync/async boundary pattern)
4. build_specialist_agents() reads self._github_token synchronously
5. GitHubIntelAgent.build_tools(github_token=token):
   - Live path: inject Bearer <github_token> into httpx.AsyncClient
   - FunctionTools call GitHub REST API directly (search repos, commits, issues)
   - GraphQL API available for deeper analytics
6. Triage routes to github_intel_agent if token present; else graceful degradation
7. LLM analyzes engineering activity, commit velocity, issue backlog
```

### 6.2 End-to-End Authentication Flow

```
Phase 1 — OAuth Authorization Code Flow:
Browser          Backend                  GitHub
  |                |                        |
  |--GET /api/auth/github (Entra token)--->  |
  |                |--- validate Entra JWT   |
  |                |--- build HMAC state    |
  |<--302 redirect to github.com/oauth/authorize-->|
  |-------------------------------------------->|
  |<--user authorizes, 302 to /callback + code-->|
  |                |<---code + state---------|
  |                |--- HMAC verify state
  |                |--- POST /login/oauth/access_token
  |                |<-- { access_token }
  |                |--- store in Cosmos (keyed by oid)
  |<--302 ?github_connected=true---|

Phase 2 — Per-request token retrieval:
PortfolioOrchestrator
  |--- CosmosDB.read_item("oid-github", partition_key=oid)
  |<-- github_access_token
  |--- inject as Authorization: Bearer <github_token> on httpx.AsyncClient
  |--- GitHubIntelAgent FunctionTools call GitHub REST API
```

**CSRF protection:** The HMAC-signed state parameter encodes the user's `oid` and a
timestamp. The backend is stateless — no server-side session is needed. The signature
prevents tampering; the 10-minute expiry closes replay attacks.

**Timing-safe comparison:** `hmac.compare_digest(sig, expected_sig)` is used instead
of `sig == expected_sig` to prevent timing side-channel attacks on the signature check.

### 6.3 MCP Pattern — Pattern 2 (External Vendor MCP with Per-User OAuth)

| Property | Value |
|---|---|
| MCP host | External — api.githubcopilot.com |
| Auth mechanism | GitHub OAuth2 access token (per user) |
| Token storage | Cosmos DB vendor-oauth-tokens container |
| User identity propagated? | Yes — GitHub's own identity system |
| RLS | GitHub enforces per-user visibility |
| CSRF protection | HMAC-signed state, 10-min window |
| Graceful degradation | Stub tool returns connect-prompt if token absent |
| Data classification | PUBLIC (aggregated OSS signals) |

**Implementation note:** The current code uses direct GitHub REST API `FunctionTool`
calls rather than the `MCPStreamableHTTPTool` pointing at `api.githubcopilot.com/mcp/`.
The `build_tools` method can be toggled to the official GitHub MCP endpoint by constructing
`MCPStreamableHTTPTool(url="https://api.githubcopilot.com/mcp/", http_client=...)` with the
token-bearing httpx client. The REST path was preferred for explicit control over which
endpoints and toolsets are exposed.

### 6.4 Architectural Best Practices Applied

- **Vendor identity isolation:** GitHub OAuth tokens never interact with Entra identity; the two systems remain independent.
- **Stateless OAuth flow:** HMAC-signed state eliminates the need for server-side session storage during the authorization code exchange.
- **Token stored server-side:** GitHub token never touches the browser after the OAuth flow; the frontend only receives `?github_connected=true`.
- **Async/sync boundary pattern:** `_fetch_github_token()` is awaited before `build_specialist_agents()` is called synchronously, satisfying the Agent Framework's synchronous agent builder requirement.
- **Defense in depth disconnection:** `DELETE /api/auth/github` revokes and deletes the token from Cosmos, stopping further access without needing to revoke the GitHub OAuth App authorization.
- **Rate-limit awareness:** Authenticated GitHub requests get 5,000 req/hr vs 60/hr anonymous. The agent operates at the authenticated tier by default.
- **Search API over org endpoint:** Uses GitHub Search API instead of `/orgs/{org}/repos` to avoid OAuth App access restrictions that block third-party apps from listing organization repositories.

---

## 7. Handoff Routing

**Sample prompts:**
- "What does the latest non-farm payroll mean for rate expectations?"
- "Are bank stocks attractive given the current rate environment?"
- "How is dollar strength affecting emerging market equities?"

### 7.1 End-to-End Data Flow

These prompts are designed to exercise the **triage → handoff** routing mechanism.
The prompts span multiple domains (macro economics + equity analysis) so the triage
agent must reason about which specialist best handles the intent.

```
1. POST /api/chat/message (mode: "handoff")
2. HandoffBuilder creates a conversation starting with triage_agent
3. triage_agent receives TRIAGE_INSTRUCTIONS system prompt + user message
4. triage_agent optionally augments with RAG (Azure AI Search context provider)
5. triage_agent reasons about the domain:
   - "non-farm payroll... rate expectations" → economic_agent
   - "bank stocks... rate environment" → could be market_intel_agent or economic_agent
   - "dollar strength... emerging markets" → market_intel_agent
6. Handoff event emitted: { type: "handoff", from: "triage_agent", to: "<specialist>" }
7. Specialist agent receives the full conversation history
8. Specialist completes the query using its tools
9. SSE stream: handoff event then agent_response chunks
10. Frontend UI renders AgentBadge showing which specialist responded
```

**Comprehensive escalation fallback:** If the triage agent returns the string
`"COMPREHENSIVE_ANALYSIS_REQUESTED"` and no handoff occurred (i.e. the LLM
decided multi-agent is needed), `run_handoff()` automatically escalates to
`run_comprehensive()` — all specialists run concurrently.

### 7.2 Role of Azure AI Search in Triage

The triage agent is wired with an `AzureAISearchContextProvider` pointing at the
`portfolio-research` index. Before routing, the triage agent can retrieve relevant
research documents to inform its decision. This is the RAG layer — research notes,
investment theses, or market analyses stored in the index augment the routing decision
and allow the triage agent to provide richer context to specialist agents.

### 7.3 Authentication Flow

Identical to whichever specialist agent the triage routes to. The handoff routing
itself requires no special authentication beyond the initial Entra token validation.

### 7.4 Architectural Best Practices Applied

- **Single-responsibility triage:** The triage agent only routes; it never fetches data itself. TRIAGE_INSTRUCTIONS includes `NEVER attempt to access portfolio data yourself`.
- **Intent detection via LLM:** Avoids brittle keyword matching; the LLM can interpret paraphrases, cross-domain queries, and ambiguous intent.
- **Prompt injection protection:** Triage SECURITY RULES instruct the agent to return `"REQUEST_BLOCKED"` if it detects injection attempts — this is caught by `check_user_message()` before processing and by the triage agent as a secondary layer.
- **Security rules in triage system prompt:** Double-layer protection — guardrail middleware + NL instruction in the system prompt.
- **Conversation history threading:** Prior messages are loaded from CosmosDB and passed to both the triage agent and the specialist, maintaining context across turns.

---

## 8. ESG Advisor

**Sample prompts:**
- "What is the ESG risk score for Microsoft and how does it compare to its tech peers?"
- "Are there any ESG controversies or governance flags I should know about for Tesla?"
- "Benchmark the ESG performance of MSFT, AAPL, and GOOGL against their sector peers"

### 8.1 End-to-End Data Flow

```
1. POST /api/chat/message → Triage routes to esg_advisor_agent
   (matches: "ESG scores, sustainability ratings, carbon footprint, governance metrics")
2. ESGAdvisorAgent is a regular Agent wrapping a Python tool:
   async def query_esg_advisor(query: str) -> str
3. LLM calls query_esg_advisor("...user's question...")
4. Tool function instantiates A2AAgent(url=esg_advisor_url):
   - POST http://esg-advisor:8010/  (A2A JSON-RPC)
   - body: { jsonrpc: "2.0", method: "tasks/send", params: { message } }
5. A2A ESG server (LangChain ReAct):
   - Receives JSON-RPC task
   - ReAct agent calls its own tools:
     - get_esg_scores(ticker)        → yf.Ticker(t).info → ISS governance scores
     - get_esg_peer_comparison(...)  → multi-ticker governance comparison
     - get_controversy_analysis(...) → risk flags, high-risk dimension detection
   - LangChain synthesizes ESG analysis
   - A2A response via TaskStatusUpdateEvent + TaskArtifactUpdateEvent
6. query_esg_advisor tool returns response.text to the wrapping Agent
7. Agent streams answer via SSE → browser
```

**A2A Transport model:**
- The A2A protocol uses JSON-RPC 2.0 over HTTP POST.
- `A2AAgent(url=esg_url)` auto-discovers capabilities via `GET /.well-known/agent.json`.
- The ESG server exposes an `AgentCard` describing its skills and accepted input types.
- Communication is synchronous request/response within the async context manager.

### 8.2 End-to-End Authentication Flow

```
Backend HandoffBuilder
   |
   +--> ESGAdvisorAgent (regular Agent)
          |
          +--> query_esg_advisor(query)  [FunctionTool]
                  |
                  +--> A2AAgent(url=http://esg-advisor:8010)
                  |    JSON-RPC POST /
                  |    (no Entra auth on A2A layer — internal network only)
                  |
                  +--> ESG A2A Server (LangChain ReAct)
                          |
                          +--> yfinance (Yahoo Finance public data)
                               (no auth required — public governance data)
```

**Current auth posture:** The A2A call to the ESG server is unauthenticated at the
HTTP level. The ESG server is expected to be deployed as an internal service (Container
App with `external: false` or equivalent) — relying on network isolation rather than
token-based authentication. See [Production Hardening](#12-production-hardening-recommendations)
for the recommended improvement.

### 8.3 A2A Pattern vs MCP Pattern

| Dimension | MCP (Model Context Protocol) | A2A (Agent-to-Agent) |
|---|---|---|
| Protocol | JSON-RPC over Streamable HTTP or SSE | JSON-RPC 2.0 over HTTP POST |
| Unit | Tool (function call) | Agent (full reasoning loop) |
| Response | Structured tool output | Free-form agent text + artifacts |
| Use case | Data retrieval, API calls | Delegating reasoning to a specialist agent |
| Agent Framework integration | MCPStreamableHTTPTool | A2AAgent + wrapping FunctionTool |
| Auth | OBO JWT / API key / OAuth | Network isolation (no token auth currently) |

**Why A2A for ESG instead of an MCP tool?** The ESG advisor runs a full LangChain
ReAct reasoning loop that may call multiple tools and synthesize across results. This
is agent-level reasoning, not a single function call. A2A is the appropriate transport
for delegating a reasoning task to a different agent runtime (LangChain vs Agent Framework).

### 8.4 Architectural Best Practices Applied

- **Agent wrapper pattern:** ESGAdvisorAgent is a regular Agent (not A2AAgent) so HandoffBuilder can inject it into the routing graph — HandoffBuilder requires `isinstance(agent, Agent)`.
- **Graceful absence:** `create_from_context()` returns `None` when `ESG_ADVISOR_URL` is not set; the registry build loop silently skips it. No exception propagates.
- **AgentCard capability discovery:** The A2A client fetches `/.well-known/agent.json` on first connection — explicit capability negotiation instead of hard-coded assumptions.
- **Heterogeneous LLM support:** The ESG server supports both Azure OpenAI and OpenAI as LLM backends, selected at startup via environment variables — enabling cost-optimized smaller models for ESG scoring if desired.
- **Data source transparency:** System prompt notes that Yahoo Finance removed granular Sustainalytics data in 2025; agents use ISS governance scores as proxy and this is stated in responses.

---

## 9. Concurrent Analysis

**Sample prompts:**
- "Give me a full portfolio review with macro context and current valuations"
- "Should I rebalance given current Fed policy and my positions?"
- "Analyze my risk exposure across macro, sector, and position levels"
- "Run a comprehensive sustainability review of my portfolio including ESG scores, macro risks, and position-level exposure"

### 9.1 End-to-End Data Flow

```
1. POST /api/chat/message (requiresAuth: true — needs portfolio data)
2. Option A: Triage agent returns "COMPREHENSIVE_ANALYSIS_REQUESTED"
   → run_handoff() auto-escalates to run_comprehensive()
Option B: Frontend sends mode: "comprehensive" directly (future implementation)

3. ConcurrentBuilder runs ALL specialist agents simultaneously:
   - economic_agent      → Alpha Vantage macro data
   - market_intel_agent  → Bing-grounded news
   - portfolio_agent     → OBO → Portfolio MCP → holdings, risk
   - private_data_agent  → OBO → Yahoo Finance MCP → quotes, fundamentals
   - github_intel_agent  → GitHub REST API (if connected)
   - esg_advisor_agent   → A2A → LangChain ReAct → governance scores

4. Each agent runs its full tool-calling loop in parallel async tasks
5. All agents complete (or timeout) and return their partial analyses
6. Synthesis agent receives all partial analyses:
   - Structures output into 6-section advisory report:
     1. Portfolio Snapshot
     2. Market Context
     3. Macro Environment
     4. ESG & Sustainability Profile
     5. Key Risks and Opportunities
     6. Actionable Recommendations
7. SSE stream: agent_response chunks from each specialist + synthesis
8. Frontend renders all AgentBadge indicators and final synthesis
```

### 9.2 End-to-End Authentication Flow

All authentication flows from the individual agents execute concurrently:

```
Single Entra token (raw_token)
       |
       +-- OBOAuth(scope=portfolio.read) → Portfolio MCP
       |
       +-- OBOAuth(scope=market.read)    → Yahoo Finance MCP
       |
       +-- Backend API key               → Alpha Vantage MCP
       |
       +-- Managed Identity              → Bing / Foundry
       |
       +-- GitHub OAuth token (Cosmos)   → GitHub API
       |
       +-- [No auth]                     → ESG A2A server (internal)
```

Each OBO exchange is independent — the same raw user token is used as
`user_assertion` for each exchange, producing distinct audience-scoped tokens for
each MCP server. OBO tokens are not shared between agents.

### 9.3 Compaction in Long Sessions

For multi-turn comprehensive sessions, the `TokenBudgetComposedStrategy` compaction
pipeline keeps the most recent 100,000 token-equivalent characters in the conversation
window and summarises older turns using `SlidingWindowStrategy(keep_last_groups=20)`.
This prevents context window overflow in iterative deep-dive conversations.

### 9.4 Synthesis Agent Design

```python
instructions = """
You are a senior portfolio advisor. Synthesize findings into:
1. Portfolio Snapshot
2. Market Context
3. Macro Environment
4. ESG & Sustainability Profile
5. Key Risks and Opportunities
6. Actionable Recommendations (with specific rationale)
"""
```

The synthesis agent receives all specialist outputs as conversation history — it does not
call tools itself. It purely reasons over the multi-agent context to produce a coherent
investment recommendation.

### 9.5 Architectural Best Practices Applied

- **Fan-out/fan-in concurrency:** ConcurrentBuilder parallelizes all specialist agents, reducing total response time from sum of sequenced calls to max of concurrent calls.
- **Single OBO token per downstream service:** No token is reused across different MCP servers; each exchange produces an audience-scoped token independent of the others.
- **Synthesis isolation:** The synthesis agent has no tools — it cannot accidentally call downstream services or exfiltrate data while composing the final report.
- **Structured output mandate:** The synthesis agent's instructions force a structured 6-section report, making the response predictable and auditable.
- **Checkpoint persistence:** `azure_cosmos_checkpoints_container` stores workflow state for long-running comprehensive analyses, enabling resume on transient failures.

---

## 10. Cross-Cutting: MCP Pattern Reference

### Three Patterns at a Glance

| Pattern | Used By | Auth Mechanism | User Identity | Data Sensitivity |
|---|---|---|---|---|
| 1a: Private MCP + OBO | Portfolio Data, Real-time Quotes | Entra OBO JWT (RS256 JWKS) | Propagated via oid claim | CONFIDENTIAL / PUBLIC |
| 1b: External Public MCP + API Key | Economic Data | Backend API key in URL | Not propagated | PUBLIC |
| 2: External Vendor MCP + Per-user OAuth | GitHub Intelligence | GitHub OAuth2 access token | GitHub identity | PUBLIC (aggregated) |

### Decision Matrix — Choosing a Pattern

```
Is the MCP server inside your Azure tenant?
 YES → Does it return user-specific confidential data?
        YES → Pattern 1a (OBO) — user identity must be propagated
        NO  → Pattern 1a (OBO) still preferred for audit trail;
              or Pattern 1b (API key) if OBO setup is not feasible
 NO  → Does the vendor have Entra integration?
        NO  → Does the vendor require per-user access tokens?
               YES → Pattern 2 (vendor OAuth)
               NO  → Pattern 1b (backend API key)
```

### MCP Authentication Layers

Every MCP server in this system implements the following authentication stack:

```
Layer 1 — Transport       : HTTPS (Container Apps TLS termination)
Layer 2 — MCP Protocol    : FastMCP auth=<verifier> (per-request token validation)
Layer 3 — Scope check     : check_scope("portfolio.read" | "market.read")
Layer 4 — Audience check  : aud must equal api://<MCP_CLIENT_ID>
Layer 5 — Issuer check    : iss must equal https://login.microsoftonline.com/{tenant}/v2.0
Layer 6 — Data layer RLS  : SQL WHERE user_id = oid  (portfolio only)
```

---

## 11. Cross-Cutting: AuthN and AuthZ Best Practices Applied

### JWT Validation (RS256 JWKS)

- **Full RS256 signature verification** using `python-jose` — no HS256 or `alg:none` accepted.
- **Audience validation:** `aud` claim must match `entra_backend_client_id`.
- **Issuer validation:** `iss` claim must match `https://login.microsoftonline.com/{tenant}/v2.0`.
- **Expiry validation:** `exp` and `nbf` claims enforced.
- **JWKS caching with key rotation:** JWKS is cached at module level; `kid` mismatch flushes cache and triggers re-fetch on next request — handles Entra's key rotation (typically every 6 weeks).

### AuthContext Design

- Single validation pass per request — `EntraJWTValidator.validate()` called once by `require_auth_context`, not twice.
- `AuthContext { claims, raw_token }` travels as one object through the request lifecycle.
- `raw_token` (the original signed JWT bytes) is preserved for the OBO exchange — claims alone cannot be re-assembled into a valid JWT.

### On-Behalf-Of (OBO) Flow

- Backend acts as a confidential client; `entra_client_secret` is stored in Key Vault.
- Each downstream MCP has its own Entra app registration with a unique audience (`api://<MCP_CLIENT_ID>`).
- Token is never passed through unchanged — audience isolation prevents confused deputy attacks.
- OBOAuth auto-refreshes on HTTP 401 from the MCP server.

### GitHub OAuth CSRF Protection

- Stateless HMAC-signed state (`hmac.new(secret, payload, sha256)`).
- State encodes `{oid, timestamp}` — user identity survives the redirect without a server-side session.
- 10-minute expiry window; `hmac.compare_digest` for timing-safe comparison.

### Network Isolation

- Private MCP servers deployed as Container Apps with `external: false` — not reachable from public internet.
- Backend-to-MCP communication over the Container Apps environment internal network.
- Only the FastAPI backend and static frontend are publicly exposed.

### Least Privilege

- Backend app registration has only the delegated permissions needed to perform OBO.
- MCP app registrations expose only the required scopes (`portfolio.read`, `market.read`).
- GitHub OAuth App scoped to `public_repo read:user` — no write permissions.
- Managed Identity used for all Azure service authentication (Cosmos, Key Vault, AI Search, Foundry).

### Audit Logging

- `audit_log()` in both MCP servers records every tool call with `caller_id`, `tool`, `duration_ms`, `outcome`.
- OAuth connect/disconnect events logged.
- Application Insights distributed traces span browser → backend → agent → MCP.

### CORS Hardening

- `allow_origins` restricted to `[settings.frontend_url, ...allowed_cors_origins]` — no wildcard.
- `allow_credentials=True` requires explicit origin list (browsers enforce this).

---

## 12. Production Hardening Recommendations

### 12.1 High Priority

#### H1 — Add PKCE to GitHub OAuth Flow
**Issue:** MCP Spec 2025-11-25 mandates OAuth 2.1 with PKCE for authorization requests.  
**Fix:**
```python
code_verifier = secrets.token_urlsafe(64)
code_challenge = base64.urlsafe_b64encode(
    hashlib.sha256(code_verifier.encode()).digest()
).rstrip(b'=').decode()
# Include in authorization redirect:
&code_challenge=<challenge>&code_challenge_method=S256
# Exchange at callback: include code_verifier in POST body
```

#### H2 — Add Bearer Token Authentication to ESG A2A Server
**Issue:** The inter-service A2A call to the ESG adviser is unauthenticated at the HTTP level.  
**Fix:** Issue a Managed Identity token scoped to the ESG server's app registration on each A2A call, or use a shared secret rotated via Key Vault.

#### H3 — Configure FastMCP as Stateless HTTP
**Issue:** FastMCP default generates server-side session IDs, violating MCP Spec M3.  
**Fix:**
```python
mcp = FastMCP(name="portfolio-db-mcp", auth=auth_provider, stateless_http=True)
```

#### H4 — Add Pydantic Validation to All MCP Tool Arguments
**Issue:** Only `symbol` fields are validated via regex; string length, enum values, and numeric ranges are not enforced.  
**Fix:** Define Pydantic input models for each tool function and validate at entry point.

#### H5 — Encrypt GitHub OAuth Tokens at Rest in Cosmos DB
**Issue:** GitHub access tokens are stored as plaintext strings in Cosmos documents.  
**Fix:** Encrypt token value with an Azure Key Vault-managed key before `upsert_item`; decrypt on `read_item`. Use envelope encryption: data key encrypted by Key Vault key.

### 12.2 Medium Priority

#### M1 — Token Expiry / Refresh for GitHub OAuth
**Issue:** GitHub OAuth tokens do not expire by default unless explicitly revoked. Fine-grained Personal Access Tokens (PATs) do expire.  
**Fix:** Store `expires_at` in the Cosmos document; check before use; trigger re-auth flow if within 24 hours of expiry.

#### M2 — Rate Limiting per User on MCP Endpoints
**Issue:** No per-user rate limiting on internal MCP servers.  
**Fix:** Add Redis-backed sliding window rate limiter (e.g. 100 tool calls / 10 min per `oid`) via FastMCP middleware or a Starlette middleware.

#### M3 — Rotate Alpha Vantage API Key via Key Vault
**Issue:** If the API key is compromised, rotation requires redeployment.  
**Fix:** Store key in Key Vault with a versioning policy; use Key Vault references in Container Apps environment variables for seamless rotation without redeployment.

#### M4 — Replace SQLite with Azure SQL / Fabric Data Agent for Portfolio MCP
**Issue:** SQLite is single-file, not suitable for concurrent writes or production scale.  
**Fix:** Replace `_db_connect()` with `pyodbc` / `aioodbc` pointing to Azure SQL or use the Microsoft Fabric Data Agent configured in the Foundry portal (already documented in `portfolio_data.py` comments).

#### M5 — Distributed Compilation for Synthesis in Concurrent Mode
**Issue:** The synthesis agent receives all specialist outputs as raw context, which may exceed token budgets for very long analyses.  
**Fix:** Implement a two-stage synthesis: each specialist produces a 200-token summary; the synthesis agent receives only summaries, enabling deterministic context sizing.

### 12.3 Lower Priority

#### L1 — Structured Logging Format (JSON)
All log statements use unstructured string format. Switching to `python-json-logger` would enable structured filtering in Application Insights / Log Analytics.

#### L2 — gRPC / Server-Sent Events for A2A Streaming
The A2A ESG server uses synchronous JSON-RPC. For long ESG analyses, streaming via Server-Sent Events (A2A supports this) would reduce perceived latency.

#### L3 — WebSocket Authentication Hardening
The WebSocket endpoint decodes JWT claims without full RS256 validation (`_decode_claims_unsafe`). In production, implement full JWKS validation for WebSocket connections or move to HTTP+SSE exclusively.

#### L4 — Content Security Policy Headers
Add `Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` headers to the FastAPI backend for defense against XSS and clickjacking.

---

## 13. Architectural Pros and Cons

### 13.1 Overall Architecture

| Aspect | Pro | Con |
|---|---|---|
| Multi-agent orchestration | Clean separation of concerns; each agent has a single data domain | Adds orchestration latency; debugging multi-hop flows requires distributed tracing |
| HandoffBuilder routing | Single LLM call routes to correct specialist; no code-based routing rules | Triage LLM can misroute on ambiguous prompts; prompt changes require careful testing |
| ConcurrentBuilder analysis | Full context gathered in parallel; response covers all domains | Higher cost per concurrent request; synthesis quality depends on all agents succeeding |
| SSE streaming | Progressive rendering; perceived latency much lower than blocking response | SSE is HTTP/1.1 only; proxies/load balancers may buffer chunks; WebSocket preferred for low-latency |

### 13.2 Authentication Architecture

| Aspect | Pro | Con |
|---|---|---|
| Entra OBO for private MCPs | User identity end-to-end; no trusted header needed; scope enforcement |  Requires 4 Entra app registrations; `client_secret` must be rotated; OBO not supported by all Entra account types |
| Managed Identity for Azure services | No secrets to manage for Cosmos, Key Vault, AI Search, Foundry | Requires correct RBAC role assignments; harder to test locally without managed identity |
| GitHub per-user OAuth tokens | User controls authorization; tokens scoped to `public_repo` only | Token store in Cosmos requires Cosmos to be available for GitHub calls; no token expiry by default |
| Backend API key for Alpha Vantage | Simple; no user identity complexity needed for public data | Single shared key; if leaked, all users are affected; no per-user rate limiting; key rotation requires redeployment |

### 13.3 MCP Architecture

| Aspect | Pro | Con |
|---|---|---|
| Private MCP (Pattern 1a) | Full Entra JWT chain; RLS at data layer; auditable; network-isolated | Setup complexity (app registrations, OBO config, JWKS validation); no off-the-shelf SaaS can be onboarded without Entra |
| External public MCP (Pattern 1b) | Simple; no user identity management; works with any third-party SaaS | All requests use the same backend identity; no per-user billing or rate limiting downstream; API key is a single point of compromise |
| Vendor OAuth MCP (Pattern 2) | Per-user access; vendor's own identity model; users control their own authorization | Full OAuth flow UX friction; token storage in Cosmos adds dependency; no token expiry mechanism; scaling to many vendors multiplies complexity |
| FastMCP for private servers | Rapid development; built-in auth provider interface | Server-side session IDs by default (must set `stateless_http=True`); Python-only; limited tooling compared to enterprise API gateways |

### 13.4 A2A for ESG Agent

| Aspect | Pro | Con |
|---|---|---|
| Language heterogeneity | ESG agent runs LangChain/LangGraph; backend runs Agent Framework — they coexist | Two runtimes to maintain, deploy, and version independently |
| Agent-level delegation | Full ReAct reasoning in ESG server; backend doesn't need to understand its tools | A2A adds HTTP roundtrip latency; debugging spans two framework boundaries |
| Graceful degradation | ESG_ADVISOR_URL unset → agent silently skipped | No fallback analysis if A2A server is down; concurrent analysis silently loses ESG context |
| Protocol standardization | A2A is a Google-backed open spec; vendor-agnostic | A2A ecosystem tooling still maturing; limited production observability compared to direct tool calls |

### 13.5 Data Model

| Aspect | Pro | Con |
|---|---|---|
| Cosmos DB for sessions | Serverless, globally distributed, schemaless; partition by `user_id` for locality | Point-in-time restore requires backup configuration; Cosmos SDK async is complex; RU cost can spike on large message history |
| SQLite in portfolio MCP | Zero external dependency for dev/testing; deterministic seeded data | Not production-ready; no concurrent write support; file path management in containers is error-prone |
| In-memory synthetic data fallback | Enables demo without any database setup | Data resets on pod restart; not suitable for any persistent analysis |

### 13.6 Observability

| Aspect | Pro | Con |
|---|---|---|
| OpenTelemetry + Application Insights | Distributed traces across backend → agent → MCP; spans visible in Azure Monitor | Sensitive data logging risk if `enable_sensitive_data=True` accidentally set; sampling needed at scale |
| Audit logs in MCP servers | Per-tool-call latency and outcome visible in structured logs | Not correlated to backend trace IDs without W3C trace propagation headers on MCP calls |

---

*Last updated: April 2026 — represents the architecture as implemented at hackathon completion.*
