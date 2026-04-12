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

## Step 2b — Add an A2A Remote Agent (LangChain / LangGraph)

> **Goal**: Build a containerised LangChain agent that speaks the A2A protocol,
> then integrate it into the orchestration workflow via the agent registry.
> The backend never imports LangChain — it treats the A2A agent as a first-class peer.
>
> Reference implementation: `a2a-agents/esg-advisor/` and `backend/app/agents/esg_advisor.py`

### Part 1 — Build the A2A server

```
I need to build a standalone A2A agent server for my application "<YOUR APP NAME>".

The agent is called "<MY AGENT NAME>" and it:
1. <describe what this agent's primary job is>
2. <describe what external APIs / data sources it calls>
3. <describe capabilities it should advertise in its agent card>

Technology:
- A2A protocol (a2a-sdk[http-server]>=0.3.23)
- LangGraph ReAct pattern (create_react_agent from langgraph.prebuilt)
- LLM: Azure OpenAI (primary) / OpenAI (fallback)

Tools to implement:
1. <tool_name>(<params>) — <what it does, what API it calls>
2. <tool_name>(<params>) — <what it does>

Tasks:
1. Use the stub at template/a2a-agents/my-a2a-agent/server.py as the starting point.
   Reference implementation: a2a-agents/esg-advisor/server.py

2. Replace the placeholder @tool functions with real implementations that call
   <your external API / data source>.
   Each tool MUST have a complete docstring (it becomes the LLM function spec).

3. Update SYSTEM_PROMPT to describe the agent's role and available tools.

4. Update AGENT_CARD:
   - name: "<MY AGENT NAME>"
   - description: "<one-sentence description>"
   - skills[]: one skill per major capability, with clear id/name/description

5. The server runs on PORT env var (default 8010). It exposes:
   POST /                        A2A JSON-RPC (called by A2AAgent in the backend)
   GET  /.well-known/agent.json  Agent card

6. Create requirements.txt based on template/a2a-agents/my-a2a-agent/requirements.txt.
   Add any extra packages your tools need.

7. Create Dockerfile based on template/a2a-agents/my-a2a-agent/Dockerfile.

8. Create .env (copy template/a2a-agents/my-a2a-agent/.env.example) and fill in your
   LLM credentials. DO NOT commit .env to git.

Run locally with:
  pip install -r requirements.txt
  python server.py
Verify: curl http://localhost:8010/.well-known/agent.json
```

### Part 2 — Register the A2A agent in the backend

```
I have a running A2A agent server at http://localhost:<PORT>.
I need to integrate it into the backend using the agent registry pattern.

Steps:

1. Add a URL setting to backend/app/config.py:
   my_agent_url: str = ""
   # doc: "URL of the my-agent A2A server, e.g. http://localhost:8010"
   Add the corresponding MY_AGENT_URL env var to backend/.env.

2. Create backend/app/agents/my_agent.py as a BaseAgent subclass:

   from agent_framework_a2a import A2AAgent
   from app.core.agents.base import AgentBuildContext, BaseAgent

   class MyAgent(BaseAgent):
       name = "my_agent"
       description = "<same description as the agent card>"

       @classmethod
       def create_from_context(cls, ctx: AgentBuildContext):
           url = getattr(ctx.settings, "my_agent_url", "")
           if not url:
               return None   # graceful skip when URL is not configured
           return A2AAgent(url=url, name=cls.name, description=cls.description)

   Reference: backend/app/agents/esg_advisor.py

3. Register the agent by adding ONE import to backend/app/agents/__init__.py:
   from . import my_agent  # noqa: F401

4. Update TRIAGE_INSTRUCTIONS in backend/app/workflows/workflow.py:
   Add a routing rule:
   - <describe user intent for this agent> -> my_agent

5. Restart the backend. The new agent is automatically picked up by
   build_specialist_agents() via the registry -- no other workflow changes needed.

Test with: Ask a question that should route to my_agent. Confirm the request
reaches the A2A server (check its logs).
```

---

## Step 3 — Wire Up the HandoffBuilder Workflow

> **Goal**: Connect your agents into the orchestration workflow.
> The workflow uses the **agent registry** — agents self-register via `create_from_context`.
> You do NOT need to manually import each agent here; just update the triage instructions.

```
I have built the following agents for my multi-agent app "<YOUR APP NAME>":
<list each file, e.g. backend/app/agents/agent_a.py, agent_b.py, my_a2a_agent.py>

All agents are registered via their BaseAgent.create_from_context() classmethod and
imported in backend/app/agents/__init__.py.

I need to complete the HandoffBuilder workflow in
`backend/app/workflows/workflow.py`.

The triage agent should route based on these rules:
- <intent category A> -> <agent_a name>
- <intent category B> -> <agent_b name>
- (optional) <intent category C> -> <a2a agent name>

Multi-agent trigger: if the user asks for <describe when comprehensive analysis applies>
the triage agent should respond with "COMPREHENSIVE_ANALYSIS_REQUESTED".

Tasks:
1. Update TRIAGE_INSTRUCTIONS with the routing rules above.
   Keep SECURITY RULES and MULTI-AGENT TRIGGER sections unchanged.
   The routing rule for each A2A agent must use the exact name= string from
   its BaseAgent subclass (e.g. "my_agent").

2. Verify that build_specialist_agents() already uses the registry pattern:
     import app.agents          # side-effect: triggers registration
     from app.core.agents.base import AgentBuildContext, BaseAgent
     ctx = AgentBuildContext(client=..., settings=..., user_token=..., ...)
     return [agent for cls in BaseAgent.registered_agents().values()
             if (agent := cls.create_from_context(ctx)) is not None]
   If the stub still contains raise NotImplementedError, replace it with
   the pattern above (reference: backend/app/workflows/portfolio_workflow.py).

3. (Optional) Implement run_comprehensive() using ConcurrentBuilder that runs
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
    color: "text-<tailwind-color>-400"
    prompts: ["<question 1>", "<question 2>", "<question 3>"]
    requiresAuth: false

  <Group 2>
    label: "<capability name>"
    badge: "<data source>"
    color: "text-<tailwind-color>-400"
    prompts: ["<question 1>", "<question 2>", "<question 3>"]
    requiresAuth: true   (if this capability uses confidential data)

  If you added an A2A remote agent (Step 2b), also add a group for it:
  <A2A Group>
    label: "<A2A agent capability name>"
    badge: "A2A / LangChain agent"
    color: "text-lime-400"              (lime signals an external/remote agent)
    prompts: ["<question 1>", "<question 2>", "<question 3>"]
    requiresAuth: false
  Reference: frontend/src/components/ChatPanel.tsx ESG Advisor group

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
