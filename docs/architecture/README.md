# Portfolio Advisor Platform — Architecture

## System Overview

This platform demonstrates a **multi-agent orchestration** pattern for financial advisory using
Microsoft Agent Framework v1.0.0 and Azure AI Foundry (Response API v2).

```
User (React SPA + MSAL)
        |
        | HTTPS / SSE streaming
        v
FastAPI Backend (Container Apps)
        |
   HandoffBuilder Workflow
        |
   +----+----+----+----+
   |    |    |    |    |
 Triage  MI  PD  Eco  Priv
 Agent  Agt Agt  Agt  Agt
        |    |         |
      Bing  Portfolio  Yahoo
    Grounding  DB MCP  Finance
              (int.)   MCP
      AI Search RAG
   (research docs)
```

### Agent Roster

| Agent | Data Class | Primary Tool | Purpose |
|-------|-----------|-------------|---------|
| `triage` | PUBLIC | AI Search (RAG) | Route user intent to specialist |
| `market_intel` | PUBLIC | Bing Grounding | Market news, sector trends, analyst ratings |
| `portfolio` | CONFIDENTIAL | Portfolio DB MCP | User holdings, performance, allocation |
| `economic` | PUBLIC | FRED MCP | Macro indicators, Fed policy, GDP, CPI |
| `private_data` | PUBLIC | Yahoo Finance MCP | Real-time quotes, fundamentals, screening |
| `synthesis` | CONFIDENTIAL | — | Aggregate comprehensive analysis |

### Orchestration Patterns

**HandoffBuilder (primary)**: Triage agent analyses intent, routes to single specialist.
Fastest for focused queries. All agents set `require_per_service_call_history_persistence=True`.

**ConcurrentBuilder (comprehensive)**: All 4 specialists run in parallel, synthesis agent aggregates.
Used when user asks for comprehensive portfolio + market analysis.

### Security Boundaries

- `portfolio` agent receives `X-User-Id` header = user OID from Entra JWT
- Portfolio DB MCP enforces row-level security per user ID
- CONFIDENTIAL data never flows through PUBLIC agents
- Guardrails perform pre/post message scanning for PII and prompt injection
- All secrets in Azure Key Vault (RBAC mode, no access policies)
- Managed Identity (no stored credentials) for all Azure service connections

### Infrastructure (Bicep / azd)

```
Azure Subscription
  Resource Group: rg-portfolio-advisor-<env>
    Managed Identity
    Key Vault (RBAC)
    App Insights + Log Analytics
    Container Registry (Basic)
    Cosmos DB (Serverless)
      - conversations (TTL 30d)
      - workflow-checkpoints
    AI Search (Standard)
      - portfolio-research index
    Container Apps Environment
      - backend           (FastAPI, port 8000, external)
      - yahoo-mcp         (FastMCP, port 8001, internal)
      - portfolio-mcp     (FastMCP, port 8002, internal)
    AI Foundry Hub + Project
      - GPT-4o deployment (GlobalStandard, 50k TPM)
    Static Web App (Standard)
      - React + Vite SPA (Entra MSAL auth)
```

### Key Design Decisions (ADRs)

**ADR-01: FoundryChatClient over raw OpenAI client**
We use `FoundryChatClient` from `agent-framework-foundry` for all workflow orchestration.
This gives us native HandoffBuilder/ConcurrentBuilder integration, automatic Azure Monitor
telemetry via `configure_azure_monitor()`, and compaction support — without requiring
pre-deployed server-side agent resources.

**ADR-02: HandoffBuilder for primary routing**
The HandoffBuilder pattern with a triage agent enables intent-based routing, providing
lower latency than ConcurrentBuilder for single-intent queries (the majority).
ConcurrentBuilder is reserved for explicit comprehensive analysis requests.

**ADR-03: CosmosDB for conversation persistence**
`CosmosHistoryProvider` from `agent_framework.azure` provides per-session conversation
history with automatic TTL cleanup. Session IDs are user-scoped (`{user_oid}:{conv_id}`)
to prevent cross-user data leakage.

**ADR-04: Internal Container Apps for MCP servers**
Yahoo Finance and Portfolio DB MCP servers run as internal Container Apps (no public IP).
The backend accesses them via internal Container Apps DNS. This reduces attack surface vs.
exposing MCP endpoints publicly. Bearer token auth adds defence-in-depth.

**ADR-05: Compaction for long conversations**
`TokenBudgetComposedStrategy(token_budget=100_000)` automatically summarises older turns
when approaching the context window, enabling long advisory sessions without context loss.
