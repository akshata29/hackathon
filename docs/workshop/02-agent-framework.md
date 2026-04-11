# Workshop Module 02: Explore the Reference Implementation

## Objective

Before building your own application you need to see the end state clearly.
In this module you will run the **Portfolio Advisor reference implementation** locally,
interact with it, and understand how the key architecture pieces fit together.

This is your target — when your own app is finished it will work the same way.

---

## Architecture Recap

```
User (React SPA + Entra Auth)
         |
         | HTTPS + Server-Sent Events (streaming)
         v
FastAPI Backend  (app/main.py)
         |
    PortfolioOrchestrator
    (HandoffBuilder workflow)
         |
   +-----+------+--------+----------+
   |     |      |        |          |
Triage Market  Portfolio Economic  Private
Agent  Intel   Agent     Agent     Data
       Agent   |                  Agent
       |       | Portfolio DB MCP    |
    Bing       | (internal)        Yahoo Finance MCP
  Grounding    |                   (internal)
               v
          AI Search RAG
        (research documents)
```

**Data classification boundaries**:
- `market_intel`, `economic`, `private_data` agents → PUBLIC data only
- `portfolio` agent → CONFIDENTIAL (user holdings, P&L)  
- CONFIDENTIAL data never flows through PUBLIC agents

---

## Step 1 — Configure Environment Variables

Copy the example environment file and fill in the values from your `azd` deployment:

```bash
cd d:\repos\hackathon\backend
Copy-Item .env.example .env
```

Now populate `.env` with your deployment outputs:

```bash
# PowerShell — fill in all core settings at once
$vals = azd env get-values --output json | ConvertFrom-Json
@"
FOUNDRY_PROJECT_ENDPOINT=$($vals.FOUNDRY_PROJECT_ENDPOINT)
AZURE_COSMOS_ENDPOINT=$($vals.AZURE_COSMOS_ENDPOINT)
AZURE_SEARCH_ENDPOINT=$($vals.AZURE_SEARCH_ENDPOINT)
APPLICATIONINSIGHTS_CONNECTION_STRING=$($vals.APPLICATIONINSIGHTS_CONNECTION_STRING)
ENTRA_TENANT_ID=$($vals.AZURE_TENANT_ID)
ENTRA_CLIENT_ID=$($vals.ENTRA_CLIENT_ID)
ENTRA_BACKEND_CLIENT_ID=$($vals.ENTRA_BACKEND_CLIENT_ID)
"@ | Set-Content d:\repos\hackathon\backend\.env -Encoding UTF8
```

---

## Step 2 — Start the MCP Servers Locally

Open two terminals:

**Terminal 1 — Portfolio DB MCP**:
```bash
cd d:\repos\hackathon\mcp-servers\portfolio-db
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
# Listening on http://0.0.0.0:8002
```

**Terminal 2 — Yahoo Finance MCP**:
```bash
cd d:\repos\hackathon\mcp-servers\yahoo-finance
pip install -r requirements.txt
MCP_AUTH_TOKEN=dev-token python server.py
# Listening on http://0.0.0.0:8001
```

---

## Step 3 — Start the Backend

Open a third terminal:

```bash
cd d:\repos\hackathon\backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Wait for: `Application startup complete.`

---

## Step 4 — Start the Frontend

Open a fourth terminal:

```bash
cd d:\repos\hackathon\frontend
npm install
npm run dev
# Vite dev server at http://localhost:5173
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## Step 5 — Interact with the Portfolio Advisor

Try each of these queries and observe which agent handles each one:

| Query | Expected agent | Why |
|-------|---------------|-----|
| "What are analysts saying about Nvidia this week?" | `market_intel` | Public market news |
| "Show me my current portfolio allocation" | `portfolio` | Confidential holdings |
| "What is the current US inflation rate?" | `economic` | Macro indicators |
| "What is Apple's P/E ratio right now?" | `private_data` | Real-time fundamentals |
| "Give me a comprehensive portfolio review" | All 4 (parallel) | Triggers ConcurrentBuilder |

Watch the **agent badges** that appear in the chat UI — they show the routing decision in real time.

---

## Step 6 — Read the Agent Routing Code

Open [backend/app/workflows/portfolio_workflow.py](../../backend/app/workflows/portfolio_workflow.py).

Find the `TRIAGE_INSTRUCTIONS` constant. This is the system prompt that tells the triage agent
how to route. Key observations:

1. **Explicit routing rules** — the triage agent is given precise categories, not a vague description.
   LLM-only routing without explicit rules is non-deterministic.
2. **COMPREHENSIVE_ANALYSIS_REQUESTED trigger** — a literal string the triage agent emits when
   it detects a multi-faceted query. The backend switches to `ConcurrentBuilder` on this trigger.
3. **REQUEST_BLOCKED** — the triage agent is instructed to detect prompt injection attempts.

---

## Step 7 — Inspect the SSE Event Stream

The backend streams results as Server-Sent Events. Watch the raw events:

```bash
# PowerShell
$body = '{"message": "What is the current inflation rate?", "session_id": "explore-test-01"}'
Invoke-RestMethod `
  -Method POST `
  -Uri "http://localhost:8000/api/chat/message" `
  -ContentType "application/json" `
  -Body $body `
  -Headers @{"Accept"="text/event-stream"}
```

You will see a stream of JSON objects. The key event types are:

| Event type | Meaning |
|-----------|---------|
| `handoff` | Triage decided which specialist agent to call |
| `text_delta` | Streaming token from the current agent |
| `tool_call` | An agent is calling an MCP tool or search provider |
| `tool_result` | The tool returned data |
| `message_complete` | Agent finished its response |

---

## Step 8 — Read the Core Agent Files

Take 10 minutes to read these files (they are the patterns you will follow):

| File | What it shows |
|------|--------------|
| [backend/app/agents/market_intel.py](../../backend/app/agents/market_intel.py) | Agent backed by a Foundry Prompt Agent (Bing Grounding) |
| [backend/app/agents/portfolio_data.py](../../backend/app/agents/portfolio_data.py) | Agent using a private MCP server with user_token |
| [backend/app/agents/economic_data.py](../../backend/app/agents/economic_data.py) | Agent using an external public MCP server |
| [backend/app/agents/private_data.py](../../backend/app/agents/private_data.py) | Agent using another external MCP server |
| [backend/app/core/workflows/base.py](../../backend/app/core/workflows/base.py) | BaseOrchestrator — do not modify; your workflow extends this |
| [backend/app/workflows/portfolio_workflow.py](../../backend/app/workflows/portfolio_workflow.py) | Domain orchestrator — the pattern you will copy |

---

## Key Concepts to Take Forward

**FoundryChatClient** — used for all HandoffBuilder and ConcurrentBuilder orchestration.
Does not require pre-deployed server-side agents in Foundry portal.

**FoundryAgent (RawFoundryAgentChatClient)** — connects to a Prompt Agent configured in the
Foundry portal (with Bing Grounding, Knowledge Bases, etc.). Used for agents that need
portal-managed integrations.

**require_per_service_call_history_persistence=True** — **every agent in a HandoffBuilder
workflow MUST set this**. Without it, conversation context breaks across handoffs.

**CompactionProvider + TokenBudgetComposedStrategy** — automatically summarises old conversation
turns when the token budget approaches the model's context window. Essential for long sessions.

**AzureAISearchContextProvider** — injects relevant search results directly into the agent's
system context on every call. The agent does not need to call a search tool explicitly.

---

## Verification Checkpoint

Before moving to Module 03, confirm:

- [ ] All 4 agents route correctly for the 4 example queries
- [ ] Comprehensive query triggers parallel execution (all agent badges appear)
- [ ] Raw SSE stream shows `handoff` events
- [ ] You can explain what `require_per_service_call_history_persistence` does

---

## Next: [Module 03 — Define Your Use-Case & Configure](./03-handoff-orchestration.md)
- [backend/app/observability/setup.py](../../backend/app/observability/setup.py) — observability setup
- [backend/app/conversation/session_manager.py](../../backend/app/conversation/session_manager.py) — Cosmos session management

## Next: [Module 03 — HandoffBuilder Orchestration](./03-handoff-orchestration.md)
