# Multi-Agent App Template

A production-ready starting point for building end-to-end multi-agent applications
using **Microsoft Agent Framework**, **Azure AI Foundry**, and **Azure infrastructure**.

The working portfolio advisor example lives in the sibling directories (`backend/`,
`frontend/`, `mcp-servers/`). This `template/` folder gives you the clean scaffold
to build your own use-case on the same foundation.

---

## What is "core" vs "domain-specific"?

| Layer | Where | What it does | You modify? |
|-------|-------|-------------|------------|
| **Core infrastructure** | `backend/app/core/` | Auth, observability, sessions, guardrails, generic routes | No — copy as-is |
| **Config** | `backend/app/config.py` | Core settings + your domain vars | Add domain vars |
| **App wiring** | `backend/app/main.py` | FastAPI app, route mounting | Add your routes |
| **Agents** | `backend/app/agents/` | Specialist agents for your domain | Implement fully |
| **Workflow** | `backend/app/workflows/workflow.py` | HandoffBuilder / ConcurrentBuilder | Implement fully |
| **Domain routes** | `backend/app/routes/domain.py` | Your data REST endpoints | Implement fully |
| **MCP server** | `mcp-servers/my-mcp/` | Private data access via MCP | Implement fully |
| **Frontend prompts** | `frontend/src/components/ChatPanel.tsx` | Sidebar example prompts | Update PROMPT_GROUPS |
| **Infrastructure** | `infra/` (copy from example) | Bicep IaC — all Azure resources | Rename parameters |

---

## Quick Start

### 1. Copy the template into a new project

```powershell
# Copy the template directory to your new project location
Copy-Item -Recurse template\ my-new-app\
cd my-new-app
```

### 2. Copy the shared infrastructure (IaC, scripts, evaluations)

The following directories are use-case-agnostic and should be copied directly
from the portfolio example:

```powershell
Copy-Item -Recurse ..\infra\ infra\
Copy-Item -Recurse ..\scripts\ scripts\    # then customize setup-foundry.py and seed scripts
Copy-Item -Recurse ..\evaluations\ evaluations\
Copy-Item ..\azure.yaml .
Copy-Item ..\docker-compose.aspire.yml .
```

### 3. Follow the coding prompts in order

Open `docs/coding-prompts/README.md` and work through the steps:

1. **Step 1**: Define your use-case, rename all placeholders, configure settings
2. **Step 2**: Build your first specialist agent
3. **Step 3**: Wire agents into the HandoffBuilder workflow
4. **Step 4**: Build your private MCP server (if you have confidential data)
5. **Step 5**: Add remote/public MCP or REST API tools (public data)
6. **Step 6**: Add domain data REST endpoints for the dashboard
7. **Step 7**: Customize the React frontend prompt groups and dashboard
8. **Step 8**: Seed your search index and local data
9. **Step 9**: Register Foundry Prompt Agents (if using hosted tools)
10. **Step 10**: Create evaluation dataset and run evals
11. **Step 11**: Add domain-specific guardrail extensions

---

## Architecture

```
User (React SPA + MSAL)
        |
        | HTTPS / SSE streaming
        v
FastAPI Backend  (app/main.py)
  |-- Core routes (app/core/routes/)      <- NEVER MODIFY
  |-- Domain routes (app/routes/)         <- YOUR CODE
        |
    AppOrchestrator (app/workflows/workflow.py)
        |
    HandoffBuilder
        |
   +-----------+
   |           |
 Triage     Agent A     Agent B     ...
 Agent        |           |
           (tools)     (tools)
           MCP / FunctionTool / Foundry hosted agent
```

### Core infrastructure (`app/core/`)

| Module | Purpose |
|--------|---------|
| `core/auth/middleware.py` | Entra ID JWT validation — `require_authenticated_user`, `maybe_authenticated_user` |
| `core/conversation/cosmos_session_store.py` | Per-user chat session persistence in Cosmos DB |
| `core/conversation/session_manager.py` | CosmosHistoryProvider wiring for agent history |
| `core/guardrails/policy.py` | PII detection, prompt injection blocking, data boundary enforcement |
| `core/observability/setup.py` | OpenTelemetry + Azure Monitor configuration |
| `core/routes/health.py` | `GET /health` endpoint |
| `core/routes/sessions.py` | `GET/DELETE /api/sessions` endpoints |

---

## Running locally

### Backend

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env   # fill in your values
uvicorn app.main:app --reload --port 8000
```

### Aspire Dashboard (local observability)

```powershell
# From workspace root
.\run_aspire_dashboard.bat
# Open http://localhost:18888 to view traces
```

### MCP Server

```powershell
cd mcp-servers\my-mcp
pip install -r requirements.txt
python server.py
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

---

## Key design decisions inherited from the example

1. **HandoffBuilder for primary orchestration** — triage routes to the cheapest specialist.
   All agents set `require_per_service_call_history_persistence=True`.

2. **ConcurrentBuilder for comprehensive analysis** — optional; add when users need
   a holistic view combining all agents.

3. **TokenBudgetComposedStrategy** — compacts conversation history to stay within
   token limits on long sessions.

4. **CosmosHistoryProvider** — persists agent conversation turns, enabling multi-turn
   context across sessions without keeping state in memory.

5. **Managed Identity everywhere** — all Azure service connections use DefaultAzureCredential.
   No secrets in code or environment except during local development.

6. **Data classification boundaries** — PUBLIC agents never receive CONFIDENTIAL data.
   The `assert_data_boundary()` guard in `core/guardrails/policy.py` enforces this.
