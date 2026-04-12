# Portfolio Advisor Platform — Architecture

> **Related docs:**
> - [Authentication & MCP Integration Patterns](./auth-and-mcp-patterns.md) — OBO, vendor OAuth, JWT validation deep-dive
> - [Workshop guide](../workshop/) — step-by-step setup and coding exercises

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Why This Architecture — Rationale](#2-why-this-architecture--rationale)
3. [Advantages, Trade-offs & Limitations](#3-advantages-trade-offs--limitations)
4. [Why MCP — and What Each Server Showcases](#4-why-mcp--and-what-each-server-showcases)
5. [Authentication & Authorization Decisions](#5-authentication--authorization-decisions)
6. [Component Deep-Dives](#6-component-deep-dives)
   - [CosmosDB — Four Containers, Four Concerns](#61-cosmosdb--four-containers-four-concerns)
   - [Azure AI Foundry & Agent Framework](#62-azure-ai-foundry--agent-framework)
   - [Azure AI Search (RAG)](#63-azure-ai-search-rag)
   - [Container Apps & Internal Networking](#64-container-apps--internal-networking)
   - [Observability](#65-observability)
   - [Guardrails & Content Safety](#66-guardrails--content-safety)
7. [Key Design Decisions (ADRs)](#7-key-design-decisions-adrs)
8. [Gotchas — Per-Component Pitfalls](#8-gotchas--per-component-pitfalls)
9. [Potential Future Changes](#9-potential-future-changes)

---

## 1. System Overview

This platform demonstrates a **multi-agent orchestration** pattern for financial advisory using
Microsoft Agent Framework v1.0.0 and Azure AI Foundry (Response API v2).

```
User (React SPA + MSAL)
        |
        |  HTTPS + Bearer <Entra token>   (SSE streaming back)
        v
Azure Static Web App (CDN-cached, global edge)
        |
        | HTTPS + Bearer (forwarded)
        v
FastAPI Backend  [Container Apps — external ingress]
        |
        |  JWT validation (JWKS RS256)  -->  AuthContext { claims, raw_token }
        |
   PortfolioOrchestrator
        |
        +-- HandoffBuilder (primary: triage -> 1 specialist)
        |         |
        |     TriageAgent  [AI Search RAG]
        |         |  handoff
        |         +---> MarketIntelAgent   [Bing Grounding, Foundry Prompt Agent]
        |         +---> PortfolioDataAgent [Portfolio DB MCP  -- OBO auth]
        |         +---> EconomicDataAgent  [Alpha Vantage MCP -- API key]
        |         +---> PrivateDataAgent   [Yahoo Finance MCP -- OBO auth]
        |         +---> GitHubIntelAgent   [GitHub MCP        -- per-user OAuth]
        |
        +-- ConcurrentBuilder (comprehensive: all 4 specialists in parallel)
                  |
              SynthesisAgent  [aggregates all specialist responses]

                  |
    CosmosDB   --|--  Conversation history (CosmosHistoryProvider)
                 |--  Workflow checkpoints (CosmosCheckpointStorage)
                 |--  Chat sessions UI store
                 |--  Vendor OAuth tokens (GitHub)
```

### Agent Roster

| Agent | Data Class | Primary Tool | Notes |
|-------|-----------|-------------|-------|
| `triage` | PUBLIC | AI Search (RAG) | Routes intent; escalates to ConcurrentBuilder if comprehensive analysis is detected |
| `market_intel` | PUBLIC | Bing Grounding | Foundry Prompt Agent — Bing tool is server-side, not client-side |
| `portfolio` | CONFIDENTIAL | Portfolio DB MCP | OBO-authenticated; SQLite RLS per user |
| `economic` | PUBLIC | Alpha Vantage MCP | Hosted remote MCP; backend API key only |
| `private_data` | PUBLIC | Yahoo Finance MCP | OBO-authenticated; real-time quotes |
| `github_intel` | PUBLIC | GitHub MCP | Per-user GitHub OAuth token; graceful degradation |
| `synthesis` | CONFIDENTIAL | — | ConcurrentBuilder aggregator only |

### Orchestration Modes

**HandoffBuilder (primary):** Triage agent analyses intent, routes to one specialist.  
Optimal for the majority of queries which have a single domain.  
All agents set `require_per_service_call_history_persistence=True` so conversation history
is preserved across turns.  
Reference: [Handoff orchestration sample](https://github.com/microsoft/agent-framework/blob/main/python/samples/03-workflows/orchestrations/handoff_simple.py)

**ConcurrentBuilder (comprehensive):** All specialists run in parallel; `SynthesisAgent`
aggregates their outputs.  Triggered either explicitly by the user or automatically when
the triage agent's accumulated response contains `comprehensive_trigger` text without a
clean handoff.  
Reference: [Concurrent orchestration samples](https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows/orchestrations)

### Infrastructure at a Glance

```
Azure Subscription
  Resource Group: rg-portfolio-advisor-<env>
    User-Assigned Managed Identity          (zero stored credentials)
    Key Vault (RBAC mode)                   (client secrets, API keys)
    App Insights + Log Analytics            (OTel traces + metrics)
    Container Registry (Basic)             (Docker images via azd)
    Cosmos DB (Serverless)
      containers:  conversations (ttl 30d) | workflow-checkpoints (ttl 24h)
                   chat-sessions (ttl 90d) | vendor-oauth-tokens (no ttl)
    AI Search (Standard + Semantic)         (portfolio-research RAG index)
    Container Apps Environment
      backend          (FastAPI, port 8000, EXTERNAL ingress)
      mcp-yahoo        (FastMCP, port 8001, INTERNAL only)
      mcp-portfolio    (FastMCP, port 8002, INTERNAL only)
    AI Foundry Hub (AIServices account)
      Project: portfolio-advisor
      Deployments: gpt-4o (GlobalStandard, 50k TPM)
                   text-embedding-3-small (Standard, 120k TPM)
      Connections: AI Search, App Insights
    Static Web App (Standard)               (React + Vite, MSAL auth)
```

---

## 2. Why This Architecture — Rationale

### Multi-agent over a single monolithic prompt

A single prompt for financial advisory would need to handle market data, user portfolio
positions, macroeconomic indicators, and engineering context simultaneously.  This
creates three problems:

1. **Context window exhaustion** — all tool calls and results live in one context.
2. **Prompt complexity** — conflicting instructions between domains degrade response quality.
3. **Security mixing** — the model can inadvertently leak or reason across data boundaries
   (e.g. user portfolio positions appearing in a market analysis response).

Specialised agents with their own system prompts, tools, and data classification labels
address all three.  Each agent only sees data it is entitled to.

Reference: [Multi-agent design guidance — Microsoft Learn](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/concepts/agents)

### Azure AI Foundry Agent Framework over raw OpenAI SDK

The Microsoft Agent Framework provides:
- `HandoffBuilder` and `ConcurrentBuilder` workflow patterns — no custom routing logic needed.
- `CosmosHistoryProvider` — per-session, multi-turn history automatically persisted to CosmosDB.
- `CosmosCheckpointStorage` — durable workflow checkpoints survive pod restarts.
- `TokenBudgetComposedStrategy` — automatic compaction without custom summarisation prompts.
- `AzureAISearchContextProvider` — RAG injection into system context without embedding boilerplate.
- `configure_azure_monitor()` — one-line OpenTelemetry wiring to Application Insights.

Reference: [Agent Framework GitHub](https://github.com/microsoft/agent-framework)

### Azure AI Foundry over standalone Azure OpenAI

Foundry provides Bing Grounding as a **server-side hosted tool** on the agent definition.
This means `MarketIntelAgent` does not need to manage a Bing Search API key or call the
Search API in application code — Foundry executes the tool server-side and injects the
results into the model context.  This pattern also applies to code interpreter and file
search tools in future.

Reference: [Bing Grounding for Foundry Agents](https://learn.microsoft.com/en-us/azure/ai-foundry/agents/how-to/tools/bing-tools)

### Container Apps over AKS or App Service

| Concern | Container Apps | AKS | App Service |
|---------|---------------|-----|-------------|
| Internal DNS between containers | Built-in (no Ingress controller) | Requires Ingress | Not supported |
| Scale-to-zero | Yes | Requires KEDA | No |
| Managed Identity support | First-class | Yes (workload identity) | Yes |
| Operational overhead | Very low | High | Low |
| MCP servers (internal-only) | `external: false` flag | NodePort + NetworkPolicy | N/A |

The `external: false` ingress flag on `mcp-yahoo` and `mcp-portfolio` is the key insight:
internal services have no public IP and are not reachable from the internet, removing the
need for network-level firewall rules.

Reference: [Container Apps managed identity](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity)

### CosmosDB Serverless over relational databases or Redis

Conversation history has unpredictable, bursty access patterns (one user session may
generate 100 operations inside 5 minutes, then go silent for hours).  Provisioned
throughput would be expensive and chronically over-allocated.  Serverless billing charges
per request unit consumed, making idle cost zero.

The document model also maps naturally to conversation turns (variable-length JSON arrays)
without schema migrations.

Reference: [Cosmos DB serverless](https://learn.microsoft.com/en-us/azure/cosmos-db/serverless)

---

## 3. Advantages, Trade-offs & Limitations

### Advantages

| Capability | How it is achieved |
|---|---|
| Low-latency focused queries | HandoffBuilder routes to one specialist — one LLM call path |
| High-quality comprehensive analysis | ConcurrentBuilder parallelises all specialists |
| No cross-user data leakage | Session IDs scoped `{oid}:{conv_id}`; CosmosDB partition per user |
| Zero stored credentials | Managed Identity for all Azure services; Key Vault for external secrets |
| Automatic scaling | Container Apps min/max replicas; CosmosDB serverless; Static Web App CDN |
| Durable long sessions | Compaction + CosmosDB checkpoints survive pod restarts and context overflow |
| Graceful degradation | GitHub agent falls back to a stub tool if OAuth not connected |
| Developer experience | Full local run without Azure (dev-mode auth bypass, SQLite portfolio, console OTel) |

### Trade-offs and Limitations

**Latency**
- Each specialist agent call involves a Foundry API round-trip.  ConcurrentBuilder adds
  parallel round-trips.  On first SSE token the user sees ~1–3 s cold-start latency.
- OBO token exchange adds ~100–200 ms on first call per session (cached thereafter).

**CosmosDB Serverless**
- Not suitable for sustained high-throughput workloads (>5,000 RU/s sustained).
  Switch to provisioned throughput for production deployments with > ~200 concurrent users.
- Serverless does not support multi-region write (single-region only).

**SQLite in Portfolio MCP**
- The portfolio MCP server (`mcp-servers/portfolio-db/`) currently uses SQLite with a
  seeded local database.  SQLite is appropriate for the demo but is not horizontally
  scalable.  In production this should be replaced with Cosmos DB or Azure SQL.

**Bing Grounding latency ceiling**
- `MarketIntelAgent` uses a `RawFoundryAgentChatClient` which bypasses the shared
  `FoundryChatClient` context.  This means it cannot share the same conversation history
  session — each Bing-grounded call is effectively stateless within Foundry's infrastructure.

**No refresh token handling for vendor OAuth**
- GitHub tokens stored in `vendor-oauth-tokens` do not expire by default, but if a user
  revokes access in GitHub settings, the next agent call silently fails rather than
  triggering a re-auth flow.

**CORS is permissive**
- `main.py` sets `allow_origins=["*"]` for development convenience.  In production this
  must be restricted to the Static Web App hostname.

---

## 4. Why MCP — and What Each Server Showcases

### Why MCP (Model Context Protocol)?

MCP is an open protocol for connecting AI agents to external data sources and tools in a
standardised way.  Unlike bespoke `FunctionTool` wrappers that must be re-implemented per
agent framework, a single MCP server exposes a consistent `POST /mcp` endpoint that any
compliant client can call.  This means:

- **Provider portability** — the same MCP server can be called by Claude Desktop, VS Code
  Copilot, and this Agent Framework backend without code changes on the server.
- **Secure transport** — authentication lives in the HTTP layer (Bearer token, API key),
  not in the protocol itself, enabling rich credential strategies.
- **Tool discovery** — clients issue a `tools/list` call to enumerate available tools
  dynamically at runtime.

Reference: [Model Context Protocol spec](https://modelcontextprotocol.io/introduction)  
Reference: [FastMCP server framework](https://github.com/jlowin/fastmcp)

### MCP Server Inventory

#### Portfolio DB MCP (`mcp-servers/portfolio-db/`)

**Showcases: Private internal MCP with Entra OBO authentication + row-level security**

This server holds user portfolio holdings in SQLite and enforces that each user can only
query their own data.  It demonstrates:

- Entra JWT validation inside `entra_auth.py` (JWKS RS256, audience check) — the same
  pattern any internal MCP server in your tenant should follow.
- Row-level security: every SQL query includes `WHERE user_id = ?` where the bind
  parameter is extracted from the validated OBO token's `oid`/`preferred_username` claim.
- The data never leaves the tenant boundary — the Container App has `external: false`.

The backend acquires an OBO token scoped to `api://<portfolio-mcp-client-id>/portfolio.read`
before each call; the MCP server rejects tokens with any other audience.

Reference: [On-Behalf-Of flow — Microsoft Learn](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)

#### Yahoo Finance MCP (`mcp-servers/yahoo-finance/`)

**Showcases: Semi-public internal MCP with selective OBO + Key Vault secret retrieval**

This server wraps the `yfinance` library to provide real-time quotes and fundamentals.
It demonstrates:

- The same Entra OBO validation as Portfolio DB, but here the data is considered PUBLIC
  (no RLS required) — showing that OBO can be used purely for service-to-service
  authentication even when the data itself is not user-specific.
- `keyvault.py` — the server uses Managed Identity to fetch a `yahoo-finance-api-key`
  from Key Vault at startup, illustrating the pattern for MCP servers that need their own
  external API secrets without storing them in environment variables.
- Scale behaviour: `minReplicas: 1` ensures the internal service is always warm.

#### Alpha Vantage MCP (remote, hosted)

**Showcases: Backend API key pattern for third-party hosted MCP endpoints**

Alpha Vantage publishes a hosted MCP endpoint at `https://mcp.alphavantage.co/mcp`.
The backend passes the API key as a URL query parameter — no local container needed.
This is the simplest MCP integration pattern and is appropriate for any SaaS provider
that offers an MCP endpoint but does not support Entra.

The API key is stored in Key Vault and injected as `ALPHAVANTAGE_API_KEY` — it is never
returned to the frontend or logged.

#### GitHub MCP (remote, `api.githubcopilot.com`)

**Showcases: Per-user third-party vendor OAuth with stateless CSRF protection**

GitHub's MCP endpoint only accepts GitHub OAuth2 access tokens — it has no relationship to
Entra and will reject OBO tokens.  This server demonstrates:

- Full OAuth2 Authorization Code flow initiated from the backend (`/api/auth/github`).
- Stateless CSRF prevention using an HMAC-signed, self-describing `state` parameter
  (no server-side session required).
- Token persistence: each user's GitHub token is stored in the `vendor-oauth-tokens`
  CosmosDB container partitioned by `user_oid`.
- Graceful degradation: if the user has not connected GitHub, the agent returns a helpful
  prompt rather than throwing an error.
- Pre-fetch pattern: because `build_specialist_agents` must be synchronous (Agent
  Framework constraint), GitHub token retrieval from CosmosDB is awaited in `run_handoff`
  before agent construction begins.

Reference: [GitHub OAuth Apps](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps)

---

## 5. Authentication & Authorization Decisions

> Full implementation details: [auth-and-mcp-patterns.md](./auth-and-mcp-patterns.md)

### Identity plane: Microsoft Entra ID throughout

All user identity assertions flow through Entra.  The frontend uses MSAL to acquire a
token scoped to the backend API app registration.  Every request carries this token;
unauthenticated requests are rejected at the middleware layer before any agent code runs.

Reference: [MSAL for React](https://learn.microsoft.com/en-us/entra/identity-platform/tutorial-single-page-app-react-sign-in)

### Four Entra app registrations

| Registration | Audience | Purpose |
|---|---|---|
| Frontend SPA | (implicit) | MSAL token acquisition; no client secret |
| Backend API | `api://<backend-client-id>` | JWT audience for incoming requests |
| Portfolio MCP | `api://<portfolio-mcp-client-id>/portfolio.read` | OBO target; RLS anchor |
| Yahoo Finance MCP | `api://<yahoo-mcp-client-id>/market.read` | OBO target; service auth |

The `scripts/post-provision.ps1` script automates creation of the backend and MCP app
registrations, including defining the custom OAuth2 scopes.  Running this script is
required after `azd provision` before the OBO flow works.

### Why OBO instead of client credentials

Client credentials (app-level) grant the backend service-wide access to all users'
portfolio data.  OBO preserves the user's identity through the call chain: the MCP server
sees exactly which user is making the request and can enforce row-level security.

If the backend used a client-credentials token to call the portfolio MCP, a bug in the
routing layer could expose one user's data to another — OBO makes that impossible because
the downstream service can only return data belonging to the user whose token was presented.

Reference: [Entra OBO flow](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow)

### Why a shared `AuthContext` dataclass

The naive approach would inject `claims` and the raw Bearer string as two separate FastAPI
dependencies, causing the JWT to be validated twice.  `AuthContext` packages both outputs
of a single validation pass — claims and the raw token string — so routes that need OBO
exchange still only validate once.

Reference: [`backend/app/core/auth/middleware.py`](../../backend/app/core/auth/middleware.py)

### Dev-mode auth bypass

When `ENTRA_TENANT_ID` is not set, `require_auth_context` decodes the JWT payload
**without** signature verification (`_decode_claims_unsafe`).  If no token is present at
all, a stable `dev@localhost` identity is returned.  This means the full code path
(session scoping, Cosmos partitioning, MCP RLS) executes locally without an Entra tenant.

The OBO module detects the empty `raw_token` and switches to a static shared bearer token
against local MCP servers.

### Key Vault for all secrets

All sensitive values (Entra client secret, Alpha Vantage API key, GitHub OAuth secret)
live in Key Vault.  Container Apps reference them as Key Vault URI references in the bicep
definition, so secrets are never stored in environment variable plaintext.  The Managed
Identity is granted `Key Vault Secrets User` role at provisioning time.

Reference: [Key Vault references in Container Apps](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets)

### Managed Identity — no stored credentials for Azure services

CosmosDB, AI Search, Container Registry, and Foundry are all accessed via
`DefaultAzureCredential` which resolves to the User-Assigned Managed Identity in
Container Apps.  The Cosmos account has `disableLocalAuth: false` in bicep (to allow
local dev with a key), but the Managed Identity is granted the
`Cosmos DB Built-in Data Contributor` SQL role — no connection strings needed in production.

Reference: [Cosmos DB RBAC](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-setup-rbac)

---

## 6. Component Deep-Dives

### 6.1 CosmosDB — Four Containers, Four Concerns

The single `portfolio-advisor` database contains four containers, each with a distinct
access pattern and lifetime:

| Container | Partition key | TTL | Used by | Purpose |
|---|---|---|---|---|
| `conversations` | `/session_id` | 30 days | `CosmosHistoryProvider` (Agent Framework) | Full turn-by-turn conversation history per session, queried by the framework on every request |
| `workflow-checkpoints` | `/workflow_id` | 24 hours | `CosmosCheckpointStorage` (Agent Framework) | Durable ConcurrentBuilder workflow state; survives pod restart during a multi-agent parallel run |
| `chat-sessions` | `/user_id` | 90 days | `CosmosSessionStore` (backend) | Per-user conversation list shown in the UI sidebar; lightweight documents (title + metadata only) |
| `vendor-oauth-tokens` | `/user_oid` | None | `VendorOAuthStore` (backend) | GitHub OAuth tokens; explicitly revoked via `DELETE /api/auth/github` |

**Why separate `conversations` and `chat-sessions`?**

`conversations` is owned by the Agent Framework and stores the full multi-turn history
in the framework's internal schema.  `chat-sessions` is owned by the application and stores
a UI-friendly summary (title, message count, timestamps) without duplicating the full
message content.  Keeping them separate means a future switch from `CosmosHistoryProvider`
to a different history backend does not break the session sidebar.

**Partition key choices**
- `conversations` is partitioned by `session_id` — the framework issues single-session
  point reads so this is always a hot-path partition key hit.
- `chat-sessions` is partitioned by `user_id` — the UI lists all sessions for one user,
  making a cross-partition fan-out query unnecessary.
- `vendor-oauth-tokens` is partitioned by `user_oid` — the `oid` (object ID) is used
  instead of `preferred_username` here because `oid` is immutable even if a user changes
  their UPN.

Reference: [Cosmos DB partitioning best practices](https://learn.microsoft.com/en-us/azure/cosmos-db/partitioning-overview)  
Reference: [Agent Framework conversation persistence sample](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/conversations)

### 6.2 Azure AI Foundry & Agent Framework

**FoundryChatClient vs RawFoundryAgentChatClient**

Most agents use a shared `FoundryChatClient` created once per request in
`BaseOrchestrator._initialize()`.  This client uses the Response API v2 with inline tool
definitions and does not require a pre-existing server-side agent resource.

`MarketIntelAgent` is the exception: it uses `RawFoundryAgentChatClient` which connects
to a **pre-deployed Foundry Prompt Agent** (`portfolio-market-intel`).  This is required
because Bing Grounding is a hosted server-side tool that must be configured on the Foundry
agent definition — it cannot be injected as a client-side tool at call time.

Reference: [Foundry Prompt Agent with tools](https://github.com/microsoft/agent-framework/blob/main/python/samples/02-agents/providers/foundry/foundry_agent_basic.py)

**Compaction**

`TokenBudgetComposedStrategy(token_budget=100_000)` is applied to all agents in
`BaseOrchestrator`.  When accumulated context approaches 100,000 tokens, the strategy
summarises older turns using the same model, discarding raw history but preserving semantic
content.  This prevents context-window errors in long advisory sessions without requiring
the application to manage summarisation logic manually.

Reference: [Compaction sample](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/compaction)

**`require_per_service_call_history_persistence=True`**

All specialist agents set this flag.  It instructs the framework to persist conversation
state to CosmosDB after every tool call, not just at the end of each turn.  This is
important for ConcurrentBuilder: if one of four parallel agent calls fails mid-way, the
checkpoint allows recovery without re-running all four.

### 6.3 Azure AI Search (RAG)

The `portfolio-research` index stores investment research documents, regulatory filings,
and market reports.  The `triage` agent uses `AzureAISearchContextProvider` to inject
relevant document excerpts into its system context before routing the user's query.

This means the triage agent can make informed routing decisions based on indexed content
— for example, if a document discusses a specific ETF, the triage agent can route to
the portfolio agent even if the user did not mention their holdings explicitly.

The index is populated by `scripts/seed-search-index.py` and uses `text-embedding-3-small`
(deployed alongside GPT-4o in `infra/modules/foundry.bicep`) for vector search.  Semantic
ranking (`semanticSearch: 'standard'` in `aisearch.bicep`) re-ranks BM25 results for
improved relevance.

Reference: [Azure AI Search context provider](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search)  
Reference: [AI Search semantic ranking](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview)

### 6.4 Container Apps & Internal Networking

The `mcp-yahoo` and `mcp-portfolio` Container Apps have `ingress.external: false`.  This
means they receive an internal DNS name of the form
`ca-mcp-portfolio-<token>.<env-default-domain>` that is only resolvable from within the
Container Apps environment.  The backend references these names via the
`PORTFOLIO_MCP_URL` and `YAHOO_MCP_URL` environment variables set in
`infra/modules/containerapps.bicep`.

There is no network security group, VNet, or private endpoint required — Container Apps
environments provide network-level isolation between internal and external apps by default.

Scale configuration: both MCP servers set `minReplicas: 1` to avoid cold-start latency
on the first agent call.  The backend sets `maxReplicas: 10` to absorb concurrent users.

Reference: [Container Apps networking](https://learn.microsoft.com/en-us/azure/container-apps/networking)

### 6.5 Observability

OpenTelemetry instrumentation is configured in two places:

1. `backend/app/core/observability/setup.py` — configures `azure-monitor-opentelemetry`
   SDK and activates `agent_framework.observability.enable_instrumentation()` which
   automatically instruments all Agent Framework HTTP calls, tool invocations, and
   handoff events.

2. `BaseOrchestrator._initialize()` — calls `client.configure_azure_monitor()` which
   retrieves the Application Insights connection string from the Foundry project
   configuration, enabling Foundry-level traces to appear alongside application traces
   in the same workspace.

For local development, the `.NET Aspire Dashboard` provides a browser-based OTel viewer
without requiring an Azure subscription (`4_run_aspire_dashboard.bat`).

`ENABLE_SENSITIVE_DATA=false` by default — this suppresses raw message content from
traces.  **Never enable in production** without explicit DLP review.

Reference: [Agent Framework observability sample](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/observability)

### 6.6 Guardrails & Content Safety

Content safety operates at two layers:

**Layer 1 — Foundry content filter (model-level)**
The GPT-4o deployment has a content filter policy applied by `scripts/setup-foundry.py`.
This automatically handles: hate speech, self-harm, sexual content, violence, prompt
injection (Prompt Shields), and protected material detection.  No application code is
needed for these categories.

**Layer 2 — Application guardrails (`core/guardrails/policy.py`)**
The application layer handles concerns that content filters cannot:
- Empty/whitespace-only input rejection before any LLM call is made.
- Data classification boundary enforcement: `CONFIDENTIAL` data cannot flow through
  `PUBLIC` agents.  `RESTRICTED` data access raises a `PolicyViolation` and is logged
  at `ERROR` level.

The clean separation means adding a new content category only requires updating the
Foundry filter policy, not modifying application code.

---

## 7. Key Design Decisions (ADRs)

**ADR-01: FoundryChatClient over raw OpenAI client**
`FoundryChatClient` from `agent-framework-foundry` provides native HandoffBuilder /
ConcurrentBuilder integration, automatic Azure Monitor telemetry via
`configure_azure_monitor()`, and compaction support — without requiring pre-deployed
server-side agent resources.  The Response API v2 endpoint format
(`https://<resource>.services.ai.azure.com/api/projects/<project>`) must be used; the
legacy `openai.azure.com` endpoint does not support the Agents API.

**ADR-02: HandoffBuilder for primary routing**
The HandoffBuilder pattern with `TriageAgent` provides intent-based routing with lower
latency than ConcurrentBuilder for single-domain queries (the majority case in testing).
ConcurrentBuilder is triggered only for explicit comprehensive requests.  The
`comprehensive_trigger` string mechanism allows this escalation to happen
transparently inside the existing `run_handoff` call without a separate route.

**ADR-03: CosmosDB for conversation persistence**
`CosmosHistoryProvider` from `agent_framework.azure` provides per-session conversation
history with automatic TTL cleanup.  Session IDs are scoped `{user_oid}:{conv_id}` to
prevent cross-user data leakage even if two users produce identical UUID values.

**ADR-04: Internal Container Apps for MCP servers**
Yahoo Finance and Portfolio DB MCP servers run as internal Container Apps (no public IP).
Bearer OBO tokens add defence-in-depth even for internal traffic.  This satisfies
zero-trust network principles without VNet complexity.

**ADR-05: Compaction for long conversations**
`TokenBudgetComposedStrategy(token_budget=100_000)` automatically summarises older turns
when approaching the context window, enabling long advisory sessions without context loss.

**ADR-06: AuthContext dataclass for single-pass JWT validation**
`require_auth_context` validates the JWT exactly once and returns both `claims` and
`raw_token` as one object.  This avoids double-validation and prevents the raw token
from being lost before it is needed for OBO.

**ADR-07: Pre-fetch pattern for async token retrieval**
`build_specialist_agents` must be synchronous (Agent Framework constraint).  Async CosmosDB
lookups (GitHub tokens) are pre-fetched in the async `run_handoff` overrides and stored
as instance attributes for synchronous methods to read.

**ADR-08: HMAC-signed stateless OAuth state parameter**
GitHub OAuth callback uses a self-describing, HMAC-SHA256-signed `state` parameter with
a 10-minute expiry instead of a server-side session.  This removes session storage as a
dependency and is CSRF-safe because tampering invalidates the signature.

---

## 8. Gotchas — Per-Component Pitfalls

### Azure AI Foundry / Agent Framework

- **Response API v2 endpoint format is mandatory.** The format is
  `https://<resource>.services.ai.azure.com/api/projects/<project>`.  If you use the
  legacy `openai.azure.com` endpoint, the Agents API returns 404 or 501.
- **`RawFoundryAgentChatClient` does not share history with `FoundryChatClient`.**
  `MarketIntelAgent` uses a separate client instance — its conversation turns are not
  included in the shared `CosmosHistoryProvider` session unless you explicitly merge them.
- **Bing Grounding must be configured on the server-side agent in Foundry,** not as a
  client-side tool.  Setting `bing_connection_id` in settings is not enough — the
  `portfolio-market-intel` agent must be created via `scripts/setup-foundry.py` first.
- **`comprehensive_trigger` must not appear in normal triage responses.**  If the phrase
  is too generic, every query escalates to ConcurrentBuilder, quadrupling latency and cost.

### CosmosDB

- **`disableLocalAuth: false` is set for development convenience.**  In a production
  hardened environment, set to `true` to force Managed Identity and block key-based access.
  Reference: [Disable local auth](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-setup-rbac#disable-local-auth)
- **Serverless has a 5,000 RU/s burst ceiling per container.**  Under load testing
  (10 concurrent users, `locustfile.py`) this is unlikely to be hit, but a production
  deployment with hundreds of concurrent users should switch to provisioned autoscale.
- **`vendor-oauth-tokens` has no TTL.**  GitHub tokens will accumulate indefinitely for
  inactive users.  Add a background job to purge tokens older than 90 days if user
  counts are large.
- **The `conversations` container TTL (30 days) is at the container level.**  Individual
  documents do not override it.  If you need per-session TTL, add a `ttl` field to each
  document.  Reference: [CosmosDB TTL](https://learn.microsoft.com/en-us/azure/cosmos-db/nosql/time-to-live)

### Entra / OBO / Auth

- **OBO requires the backend app registration to have `api://<backend-client-id>` as its
  Application ID URI**, not just a GUID client ID.  The OBO grant will return
  `AADSTS70011: The provided value for the input parameter 'scope' is not valid` if this
  is missing.
- **`post-provision.ps1` must be run after every `azd provision`** that recreates the
  app registrations.  If you delete and recreate the resource group, the app registration
  client IDs change and the environment variables must be updated.
- **The dev-mode auth bypass (`_decode_claims_unsafe`) must never reach production.**
  The guard is `if not settings.entra_tenant_id` — ensure `ENTRA_TENANT_ID` is set in
  all production Container Apps environment variables.
- **`preferred_username` can be absent** for guest accounts and service principals.
  Always fall back to `oid` as shown in `auth.user_id`.  Never use `sub` as a partition
  key — it is pairwise per-application and differs between tokens for the same user.

### Container Apps / MCP Servers

- **Internal Container Apps DNS is only resolvable from within the same environment.**
  Local development must use `localhost:<port>` via the batch files `2_run_mcp_portfolio.bat`
  and `3_run_mcp_yahoo.bat` which start the MCP servers locally.
- **`minReplicas: 0` would cause cold-start delays of 10–30 s** on the first MCP call
  after an idle period.  Both internal MCP servers use `minReplicas: 1`.
- **Container image tags are `latest` in the bicep.**  For production deployments, pin
  to a specific digest to ensure reproducible rollouts.

### GitHub OAuth / Vendor OAuth

- **The GitHub OAuth App callback URL must exactly match** `GITHUB_OAUTH_REDIRECT_URI`
  in settings (including protocol and path).  A mismatch returns `redirect_uri_mismatch`
  from GitHub.
- **GitHub tokens do not expire** (classic tokens) but the user can revoke them at any
  time in GitHub settings.  The agent silently fails with a stub response — consider
  adding a 401-triggered re-auth prompt in the frontend.
- **The `state` parameter is hex-encoded JSON** — some OAuth implementations expect a
  simple opaque string.  GitHub accepts arbitrary strings so this is safe, but document
  it if adapting the pattern for another vendor.

### Observability

- **`enable_sensitive_data=True` logs raw message content to Application Insights.**
  This would include portfolio positions, user queries, and potentially PII.
  Set to `False` (the default) in all non-development environments.
- **The Aspire Dashboard OTLP port is 18889, not 4317.**  The `4_run_aspire_dashboard.bat`
  script maps 4317 → 18889.  If you run the image without port mapping, OTel data will
  be silently dropped.

---

## 9. Potential Future Changes

### Near-term (production hardening)

| Change | Rationale | Reference |
|---|---|---|
| Replace SQLite in Portfolio MCP with Azure SQL or Cosmos DB | SQLite is not horizontally scalable; a second replica of `mcp-portfolio` would have divergent state | [Azure SQL for Container Apps](https://learn.microsoft.com/en-us/azure/azure-sql/database/connect-query-python) |
| Set `disableLocalAuth: true` on CosmosDB | Forces Managed Identity; eliminates key-based access risk | [Cosmos RBAC hardening](https://learn.microsoft.com/en-us/azure/cosmos-db/how-to-setup-rbac#disable-local-auth) |
| Restrict CORS to `frontend_url` | `allow_origins=["*"]` is acceptable in dev but required to be restricted in production | [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/) |
| Pin container image tags | `latest` is non-deterministic; pin to SHA digest in bicep | [ACA image management](https://learn.microsoft.com/en-us/azure/container-apps/revisions) |
| GitHub token refresh / re-auth prompt | Revoked GitHub tokens produce silent failures; surface re-auth in the UI | [GitHub token scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps) |
| Add `vendor-oauth-tokens` TTL cleanup job | Inactive user tokens accumulate indefinitely | [Cosmos DB change feed](https://learn.microsoft.com/en-us/azure/cosmos-db/change-feed) |

### Medium-term (capability expansion)

| Change | Rationale | Reference |
|---|---|---|
| Switch CosmosDB to provisioned autoscale | Serverless has a 5,000 RU/s burst ceiling; autoscale handles sustained load with cost predictability | [Cosmos autoscale](https://learn.microsoft.com/en-us/azure/cosmos-db/provision-throughput-autoscale) |
| Add Cosmos multi-region read replicas | Reduce global latency for conversation history reads | [Cosmos global distribution](https://learn.microsoft.com/en-us/azure/cosmos-db/distribute-data-globally) |
| Adopt MCP Authorization Server spec | The MCP spec is adding a standardised OAuth Authorization Server pattern that would replace the bespoke OBO + HMAC state code | [MCP Authorization (draft)](https://spec.modelcontextprotocol.io/specification/2025-03-26/basic/authorization/) |
| Streaming MCP responses | Current MCP calls are request-response; the MCP spec supports SSE streaming from tool calls, which would reduce time-to-first-token for portfolio queries | [MCP transports](https://modelcontextprotocol.io/docs/concepts/transports) |
| Entra External ID for B2C scenarios | If the platform is extended to retail (non-corporate) users, Entra External ID replaces the current workforce-tenant MSAL flow | [Entra External ID](https://learn.microsoft.com/en-us/entra/external-id/overview) |
| Azure API Management in front of backend | Adds rate limiting, subscription keys, and a developer portal without modifying application code | [APIM with Container Apps](https://learn.microsoft.com/en-us/azure/api-management/self-hosted-gateway-on-kubernetes-in-production) |
| A2A (Agent-to-Agent) protocol | Google's A2A protocol is emerging as a complement to MCP for inter-agent communication; the HandoffBuilder pattern could delegate to remote agents via A2A | [A2A spec](https://google.github.io/A2A/) |

### Long-term (architectural evolution)

| Change | Rationale |
|---|---|
| Replace static `triage_instructions` with dynamic intent classifier | A fine-tuned classifier would allow new specialist agents to be added without rewriting the triage system prompt |
| Per-agent CosmosDB partitioning | Today all agents share one `conversations` container; sharding by agent type would enable per-agent TTL policies and independent scaling of history storage |
| WebSocket-native streaming | Current SSE streaming is HTTP/1.1 based; a full WebSocket transport would allow bidirectional communication (e.g., the agent requesting user confirmation before executing a trade) |
