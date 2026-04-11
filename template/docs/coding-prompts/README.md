# Template Coding Prompts — Build Your Own Multi-Agent App

These prompts are designed to be pasted into GitHub Copilot (agent mode), Cursor,
or any AI coding assistant. Each prompt is **self-contained** — fill in the
`<PLACEHOLDER>` sections for your use-case, then paste the whole block.

The prompts follow the order you should implement features:
configuration → agents → workflow → data endpoints → MCP → frontend → evaluation

---

## Financial Services Use-Case Guides

Ready-to-use, end-to-end coding prompt sequences for three financial services sub-verticals.
Each guide replaces Steps 1-10 below with domain-specific, pre-filled prompts.

| Vertical | Use-Case | File |
|---|---|---|
| Capital Markets | Trade Risk Advisor — VaR, counterparty exposure, P&L attribution, FRTB capital | [capital-markets-risk.md](./capital-markets-risk.md) |
| Banking | SME Lending Advisor — credit eligibility, facility status, covenant compliance | [banking-sme-lending.md](./banking-sme-lending.md) |
| Insurance | Policy Intelligence Advisor — placement, premium, discounts, cancellation, claims removal | [insurance-policy-advisor.md](./insurance-policy-advisor.md) |

Use these guides as a starting point and adapt the agent instructions, MCP tool schemas,
and evaluation datasets to your specific data model.

---

## Step 1 — Define Your Use-Case and Configure Settings

> **Goal**: Establish your domain, rename all placeholders, and wire up environment variables.

```
I am building a multi-agent application called "<YOUR APP NAME>" using Microsoft
Agent Framework v1.0.0 and Azure AI Foundry.

The use-case is: <1-2 sentence description of what the app does>

Example user questions this app should answer:
- <question 1>
- <question 2>
- <question 3>

The app will have these specialist agents:
- <Agent A name>: handles <what it does, what data it uses>
- <Agent B name>: handles <what it does, what data it uses>
- (optional) <Agent C name>: handles <what it does>

My data sources are:
- <Source 1>: <description, public or confidential, how accessed>
- <Source 2>: <description, public or confidential, how accessed>

Tasks:
1. Update `template/backend/app/config.py`:
   - Rename azure_cosmos_database_name default to match my app
   - Rename azure_search_index_name default to match my app
   - Rename otel_service_name default to my app slug
   - Add domain-specific settings in the DOMAIN-SPECIFIC section:
     one MCP URL per private data source, relevant API key fields,
     and Foundry agent name fields for each specialist agent

2. Update `template/backend/app/main.py`:
   - Update the FastAPI title and description to match my app

3. Create a `.env.example` file listing all required environment variables
   with placeholder values and a comment explaining each.
```

---

## Step 2 — Build Your First Specialist Agent

> **Goal**: Create a domain-specific specialist agent in `backend/app/agents/`.

```
I am building a multi-agent application using Microsoft Agent Framework v1.0.0.

I need to add a specialist agent called `<agent_name>_agent` that:
1. <describe what this agent's primary job is>
2. <describe what data it fetches or tools it uses>
3. <describe its data classification: PUBLIC or CONFIDENTIAL>
4. <describe any constraints — what it must NOT do>

The agent uses:
  agent_framework.Agent            — for creating the agent
  agent_framework.FoundryChatClient — already created by the orchestrator

Tool choice (pick one):
  a) FunctionTool — wrapping Python functions that call <your API/database>
  b) MCPStreamableHTTPTool — connecting to a private MCP server at settings.<mcp_url>
  c) RawFoundryAgentChatClient — backed by a hosted Foundry Prompt Agent named
     settings.<agent_name>_agent_name

The agent MUST set `require_per_service_call_history_persistence=True` because
it participates in the HandoffBuilder workflow.

Create the file at `backend/app/agents/<agent_name>.py` following the same
pattern as the example at `backend/app/agents/market_intel.py` (option c)
or `backend/app/agents/portfolio_data.py` (option b).

The system prompt (INSTRUCTIONS constant) should:
- State the agent's role and responsibilities
- List what data classification the agent handles
- Specify what it MUST NOT do (security boundary)
- Mention the tools available and when to call them
```

---

## Step 3 — Wire Up the HandoffBuilder Workflow

> **Goal**: Connect your agents into the orchestration workflow.

```
I have built the following agents for my multi-agent app "<YOUR APP NAME>":
<list each agent file and its create_ function>

I need to wire them into the HandoffBuilder workflow in
`backend/app/workflows/workflow.py`.

The triage agent should route based on these rules:
- <intent category A> → <agent_a_name>
- <intent category B> → <agent_b_name>
- (optional) <intent category C> → <agent_c_name>

Multi-agent trigger: if the user asks for <describe when comprehensive analysis applies>
the triage agent should respond with "COMPREHENSIVE_ANALYSIS_REQUESTED".

Tasks:
1. Update TRIAGE_INSTRUCTIONS with the routing rules above
2. In run_handoff(), import and instantiate each agent using its create_ function
3. Add each agent to HandoffBuilder with .add_agent()
4. (Optional) Implement run_comprehensive() using ConcurrentBuilder that runs
   all specialist agents in parallel, then synthesises with a summary agent.
   Reference: backend/app/workflows/portfolio_workflow.py run_comprehensive()

All agents MUST set require_per_service_call_history_persistence=True.
The workflow MUST use TokenBudgetComposedStrategy for compaction.

The orchestrator class is AppOrchestrator. The chat route at
backend/app/routes/chat.py already imports and calls AppOrchestrator.run_handoff().
```

---

## Step 4 — Build Your Private MCP Server

> **Goal**: Create a FastMCP server exposing your private data to agents.

```
I need to build a private MCP server for my application "<YOUR APP NAME>" using FastMCP.

The server provides access to: <describe your data source>
Data classification: CONFIDENTIAL | PUBLIC

The server should expose these tools:
1. <tool_name>(<params>) — <what it does>, returns <return type/shape>
2. <tool_name>(<params>) — <what it does>, returns <return type/shape>
3. (optional) <tool_name>(<params>) — <what it does>

Data access:
- Data is stored in: <SQLite / PostgreSQL / REST API / Azure SQL / Cosmos DB>
- Connection details come from environment variables: <list env vars>

Security requirements:
- Bearer token authentication (use FastMCP StaticTokenVerifier)
- Row-level security: each tool must accept a user_id parameter and filter
  results to only that user's data (use the X-User-Id header pattern from
  mcp-servers/portfolio-db/server.py)

Create the server at `mcp-servers/<my-server-name>/server.py`.
Follow the same pattern as `mcp-servers/portfolio-db/server.py`.

Each tool must have a complete docstring because FastMCP sends the docstring
as the tool description to the language model.
```

---

## Step 5 — Add a Remote/Public MCP or REST API Tool

> **Goal**: Give an agent access to a public data source via MCP or direct API calls.

```
I need to add external data capabilities to my agent `<agent_name>_agent`.

The data source is: <name of the external service>
Access method (choose one):
  a) Public hosted MCP endpoint at: <URL>
     Authentication: <none / API key in URL / Bearer token>
  b) REST API at: <base URL>
     Authentication: <API key header / OAuth / none>
     Endpoints I need:
       GET <path> — <description>
       GET <path> — <description>

If using option (a) — MCPStreamableHTTPTool:
  Add a new MCPStreamableHTTPTool in the agent's create_ function.
  Store the endpoint URL in settings (e.g. settings.my_service_mcp_url).
  Reference: backend/app/agents/private_data.py

If using option (b) — FunctionTool wrapping httpx:
  Create async Python functions that call the REST API using httpx.AsyncClient.
  Wrap them with FunctionTool from agent_framework.
  Each function must have a clear docstring describing parameters and return shape.
  Reference: backend/app/agents/economic_data.py

Store any required API keys as settings fields in backend/app/config.py
and read them from environment variables. Never hardcode secrets.
```

---

## Step 6 — Add Domain Data REST Endpoints (Dashboard / UI)

> **Goal**: Expose domain data directly to the frontend (not via the agent chat).

```
My application "<YOUR APP NAME>" needs REST endpoints for the frontend dashboard
that return domain data directly without going through the agent chat.

I need these endpoints:
1. GET /api/<domain>/<resource>    — <description of what it returns>
   Authentication: <none | require_authenticated_user>
   Returns: { "<key>": [...] }

2. GET /api/<domain>/<resource>    — <description>
   Authentication: <none | require_authenticated_user>
   Returns: { "<key>": ... }

The user identity (for authenticated endpoints) comes from the Entra JWT
using the `require_authenticated_user` FastAPI dependency from
`app.core.auth.middleware`.

For authenticated endpoints, the user OID is available via:
  user: dict = Depends(require_authenticated_user)
  user_id = user.get("oid") or user.get("sub")

Create/update `backend/app/routes/domain.py`.
Wire the router into `backend/app/main.py` with prefix="/api/<domain>".

In development (no real data), return deterministic synthetic data seeded by
the user's OID so every test user sees consistent but unique data.
Reference: backend/app/routes/portfolio.py _build_user_portfolio()
```

---

## Step 7 — Customize the React Frontend

> **Goal**: Update the UI with your use-case prompts and dashboard.

```
I am customizing the React frontend for my application "<YOUR APP NAME>".

The frontend lives at `template/frontend/` (React + TypeScript + Tailwind CSS + Vite).
Auth is handled by MSAL (@azure/msal-react) — do not change authConfig.ts.

Task A — Update ChatPanel prompt groups:
  File: template/frontend/src/components/ChatPanel.tsx
  Update the PROMPT_GROUPS constant with my use-case:

  Agent capabilities:
  <Group 1>
    label: "<capability name>"
    badge: "<data source or mechanism>"
    prompts: ["<question 1>", "<question 2>", "<question 3>"]
    requiresAuth: false

  <Group 2>
    label: "<capability name>"
    badge: "<data source>"
    prompts: ["<question 1>", "<question 2>", "<question 3>"]
    requiresAuth: true   (if this capability uses confidential data)

  Also update:
  - The empty-state heading (currently "My App Assistant") to "<YOUR APP NAME>"
  - The empty-state subtitle to describe your app in one sentence

Task B — Build the domain Dashboard (optional):
  Create `frontend/src/components/Dashboard.tsx` that:
  - Calls GET /api/<domain>/<resource> endpoints from backend/app/routes/domain.py
  - Uses recharts (already installed) for any charts
  - Shows a loading skeleton when data is fetching
  - Shows an error state on failure
  - Uses fetch with the Entra Bearer token from useApiToken() hook
  Reference: frontend/src/components/Dashboard.tsx (portfolio example)
  Reference: frontend/src/hooks/useApi.ts for the token helper
```

---

## Step 8 — Seed Your Knowledge Base and Data

> **Goal**: Populate Azure AI Search and any local databases with your domain data.

```
I need to seed two data stores for my application "<YOUR APP NAME>":

1. Azure AI Search index for RAG (search-backed context for agents):
   Index name: <from settings.azure_search_index_name>
   Document shape: { "id": str, "title": str, "content": str, "source": str }
   Source documents: <describe where your documents come from>
   Task: Create/update `scripts/seed-search-index.py` to upload my documents.
   Reference: scripts/seed-search-index.py (portfolio example)

2. Local SQLite database for the portfolio MCP server (if applicable):
   Database path: set by DB_PATH env var
   Tables needed:
     <table_name>(<columns>)  — <description>
   Task: Create `scripts/seed-data.py` that creates the schema and inserts
   sample rows for at least 3 test users (use email addresses as user IDs).
   Reference: scripts/seed-portfolio-db.py

After seeding, the MCP server at `mcp-servers/<my-server>/server.py` should
read from the SQLite database (see _db_connect() pattern in
mcp-servers/portfolio-db/server.py).
```

---

## Step 9 — Create Foundry Prompt Agents

> **Goal**: Register your agents in Azure AI Foundry so they can use hosted tools.

```
I need to create Foundry Prompt Agent definitions for my application.

For each agent that uses hosted Foundry tools (Bing Grounding, Code Interpreter,
Fabric Data Agent, etc.), I need a PromptAgentDefinition created via the
Azure AI Projects SDK.

My agents that need Foundry registration:
1. Agent name in Foundry: settings.<agent_name>_agent_name (e.g. "my-app-agent-a")
   Instructions: <the INSTRUCTIONS constant from my agents/<agent_name>.py>
   Hosted tools: <BingGroundingTool / CodeInterpreterTool / FabricTool / none>

2. (repeat for each agent needing Foundry registration)

Update `scripts/setup-foundry.py` to create/update these agent definitions.
Follow the same pattern as the existing setup-foundry.py in the portfolio example.
Agents that only use MCPStreamableHTTPTool or FunctionTool do NOT need
Foundry registration (they use FoundryChatClient directly).
```

---

## Step 10 — Add Evaluation Dataset and Run Evals

> **Goal**: Build an evaluation dataset and scoring pipeline for your agents.

```
I need to create an evaluation dataset and evaluation pipeline for my
multi-agent application "<YOUR APP NAME>" using azure-ai-evaluation.

My evaluation scenarios:
- <scenario 1>: input: "<user question>", expected: "<expected output or behavior>"
- <scenario 2>: input: "<user question>", expected: "<expected output or behavior>"
- <scenario n>: ...

I want to measure:
  - Groundedness (is the answer supported by retrieved context?)
  - Relevance (does the answer address the question?)
  - (optional) Custom metric: <describe a domain-specific metric>

Tasks:
1. Create `evaluations/test-dataset.json` with at least 10 question/answer pairs
   covering all my agent capability areas.
   Schema: [{"input": "...", "expected_output": "...", "agent": "...", "tags": [...]}]
   Reference: evaluations/test-dataset.json (portfolio example)

2. Update `evaluations/run-evals.py` to:
   - Load my test-dataset.json
   - Call the chat endpoint for each test case
   - Score results using azure-ai-evaluation Groundedness and Relevance evaluators
   - Output a summary table with pass/fail per test case
   Reference: evaluations/run-evals.py (portfolio example)
```

---

## Step 11 — Add Guardrail Extensions for Your Domain

> **Goal**: Add domain-specific guardrails on top of the core PII/injection checks.

```
The core guardrails in `backend/app/core/guardrails/policy.py` already check for:
- Prompt injection patterns
- PII (SSN, credit card, email) in user input and agent responses

For my application "<YOUR APP NAME>", I need additional domain-specific checks:
1. Block messages that <describe domain-specific restriction>
   Pattern: <regex or keyword list>
   Block reason: "<human-readable message to return to the user>"

2. (optional) Block if <another domain restriction>

Tasks:
1. Create `backend/app/guardrails/domain_policy.py` with:
   - A function `check_domain_message(text: str) -> PolicyResult`
   - It imports and calls check_user_message() from app.core.guardrails.policy first
   - Then applies the domain-specific checks above
   - Returns PolicyResult(allowed=False, reason=...) on violation

2. In `backend/app/routes/chat.py`, import and call check_domain_message()
   before passing the message to AppOrchestrator.run_handoff().
   Follow how portfolio_workflow.py uses PolicyResult.
```
