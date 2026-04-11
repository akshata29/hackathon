# Workshop Module 04: Build Specialist Agents & Workflow

## Objective

Build your specialist agents and wire them into the HandoffBuilder orchestration workflow.
By the end of this module, routing is fully functional and you can test conversation flow end-to-end.

---

## Agent Framework Concepts

### How agents work

An **Agent** wraps a language model + system instructions + tools + context providers.
The framework handles conversation history, token management, and tool execution.

```python
from agent_framework import Agent
from agent_framework.foundry import FoundryChatClient

async with Agent(
    client=client,                  # shared FoundryChatClient
    name="my_agent",
    instructions="You are...",
    tools=[my_tool],                # FunctionTool, MCPStreamableHTTPTool, etc.
    context_providers=[history],    # CosmosHistoryProvider, SearchContextProvider, etc.
    require_per_service_call_history_persistence=True,  # REQUIRED for HandoffBuilder
) as agent:
    ...
```

### Three agent tool patterns

| Pattern | When to use | Reference file |
|---------|-------------|----------------|
| **RawFoundryAgentChatClient** | Agent backed by a Foundry Prompt Agent (Bing Grounding, Knowledge Base, etc.) | `backend/app/agents/market_intel.py` |
| **MCPStreamableHTTPTool** | Agent needs a private MCP data server with row-level security | `backend/app/agents/portfolio_data.py` |
| **FunctionTool** | Agent wraps a Python function calling a REST API or SDK | `backend/app/agents/economic_data.py` |

### HandoffBuilder orchestration

```
Triage Agent
  -- analyses intent
  -- routes to specialist agent
  -- can detect multi-agent requests

Specialist Agents
  -- each handles one domain
  -- can hand back to triage if query is out of scope

ConcurrentBuilder (comprehensive mode)
  -- all specialists run in parallel
  -- synthesis agent aggregates results
```

**Critical rule**: every agent in a HandoffBuilder workflow MUST set
`require_per_service_call_history_persistence=True`. Omitting this breaks context
continuity across handoffs and is a common source of bugs.

### Compaction for long conversations

GPT-4o has a 128k token context window. Financial advisory conversations with tool
results and history can approach this limit quickly.

`TokenBudgetComposedStrategy` watches the running token count and automatically
summarises older turns when the budget threshold is reached, preserving semantic
content while freeing context space.

```python
from agent_framework.compaction import CompactionProvider, TokenBudgetComposedStrategy

compaction = CompactionProvider(
    strategy=TokenBudgetComposedStrategy(token_budget=100_000)
)
# Include in agent context_providers=[history, search, compaction]
```

This is already wired in `BaseOrchestrator` — you do not need to add it manually.

---

## Step 1 — Run Coding Prompt Step 2 (First Specialist Agent)

Open GitHub Copilot Chat (agent mode). For **each** of your specialist agents, run this prompt.
Start with your most important CONFIDENTIAL agent (the one accessing private data):

> The full prompt template is in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 2.

```
I am building a multi-agent application using Microsoft Agent Framework v1.0.0.

I need to add a specialist agent called `<agent_name>_agent` that:
1. <describe what this agent's primary job is>
2. <describe what data it fetches or tools it uses>
3. Data classification: <PUBLIC or CONFIDENTIAL>
4. <describe what it must NOT do — security boundary>

Tool pattern to use: <pick one>
  a) RawFoundryAgentChatClient — backed by a hosted Foundry Prompt Agent named
     settings.<agent_name>_agent_name (use for Bing Grounding, Knowledge Bases)
  b) MCPStreamableHTTPTool — connecting to a private MCP server at settings.<mcp_url>
     (use for CONFIDENTIAL data with row-level security)
  c) FunctionTool — wrapping a Python function calling <your API or SDK>
     (use for public APIs where a full MCP server is overkill)

The agent MUST set require_per_service_call_history_persistence=True.

Create the file at `my-app/backend/app/agents/<agent_name>.py` following the same
pattern as the reference at `backend/app/agents/<closest_reference>.py`.

The INSTRUCTIONS constant (system prompt) must:
- State the agent's role and primary responsibilities clearly
- Specify the data classification and what data the agent handles
- List what it MUST NOT do (security boundary — be explicit)
- Describe the tools available and the decision logic for calling them
- Include a brief response format guideline (length, tone, structure)
```

Repeat this prompt for each of your specialist agents. Review each generated file before applying.

---

## Step 2 — Run Coding Prompt Step 3 (Wire the Workflow)

Once all agent files are created, run the workflow wiring prompt:

> The full prompt template is in [template/docs/coding-prompts/README.md](../../template/docs/coding-prompts/README.md) — Step 3.

```
I have built the following agents for my multi-agent app "<YOUR APP NAME>":
- my-app/backend/app/agents/<agent_a>.py  — creates <AgentA> class or create_<a>_agent()
- my-app/backend/app/agents/<agent_b>.py  — creates <AgentB> class or create_<b>_agent()
- my-app/backend/app/agents/<agent_c>.py  — creates <AgentC> class or create_<c>_agent()

I need to wire them into the HandoffBuilder workflow in
`my-app/backend/app/workflows/workflow.py`.

The triage agent should route based on these intent categories:
- <intent category A, e.g. "credit eligibility, loan applications"> → <agent_a_name>
- <intent category B, e.g. "facility status, repayment schedule"> → <agent_b_name>
- <intent category C, e.g. "market news, sector risks"> → <agent_c_name>

Multi-agent trigger: if the user asks for <describe what triggers comprehensive analysis,
e.g. "a full credit assessment or comprehensive borrower review">, the triage agent
should respond with "COMPREHENSIVE_ANALYSIS_REQUESTED".

Tasks:
1. Update TRIAGE_INSTRUCTIONS with the routing rules above
2. In build_specialist_agents(), instantiate each agent using its create_ function
3. Ensure all agents have require_per_service_call_history_persistence=True
4. Implement build_synthesis_agent() with a summary prompt appropriate for my domain
5. (Optional) Implement a ConcurrentBuilder comprehensive mode — reference:
   backend/app/workflows/portfolio_workflow.py
6. Set workflow_name and comprehensive_trigger class variables appropriately

The AppOrchestrator class extends BaseOrchestrator. The chat route at
my-app/backend/app/routes/chat.py already imports AppOrchestrator — do not modify chat.py.
```

---

## Step 3 — Mount Your Domain Chat Route

The template includes a stub at `my-app/backend/app/routes/domain.py`. Open `my-app/backend/app/main.py`
and confirm the chat route is properly mounted. It should already be there:

```python
from app.routes import chat, domain
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(domain.router, prefix="/api/domain", tags=["domain"])
```

---

## Step 4 — Start and Test the Wired Workflow

```bash
cd my-app\backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

Test basic routing with PowerShell:

```powershell
# Test each agent routes correctly
$tests = @(
    @{ msg="<query that should go to agent A>"; session="test-a-01" },
    @{ msg="<query that should go to agent B>"; session="test-b-01" },
    @{ msg="<query that should go to agent C>"; session="test-c-01" }
)

foreach ($t in $tests) {
    $body = $t | ConvertTo-Json
    Write-Host "Testing: $($t.msg)"
    Invoke-RestMethod -Method POST `
        -Uri "http://localhost:8000/api/chat/message" `
        -ContentType "application/json" `
        -Body $body |
        ForEach-Object { $_.content } | Select-Object -First 200
    Write-Host "---"
}
```

For each test, verify in the response events that `type: "handoff"` shows the correct agent name.

---

## Step 5 — Test the Comprehensive Mode (Optional)

If you implemented ConcurrentBuilder:

```powershell
$body = @{
    message = "<a query that should trigger COMPREHENSIVE_ANALYSIS_REQUESTED>"
    session_id = "test-comprehensive-01"
    mode = "auto"
} | ConvertTo-Json

Invoke-RestMethod -Method POST `
    -Uri "http://localhost:8000/api/chat/message" `
    -ContentType "application/json" `
    -Body $body
```

You should see multiple `handoff` events (one per parallel agent) followed by a synthesis response.

---

## Troubleshooting

**All queries route to the same agent**: The triage INSTRUCTIONS routing rules are not
specific enough. Add more concrete keywords and examples to each routing category.

**context across turns is lost**: An agent is missing `require_per_service_call_history_persistence=True`.
Check every agent in `build_specialist_agents()`.

**KeyError on settings**: A domain setting referenced in an agent file is not defined in `config.py`.
Add the missing setting with a default value.

**Agent raises AuthenticationError**: `DefaultAzureCredential()` is failing. Ensure your `.env`
has `AZURE_CLIENT_ID` set (or run in a Container App with Managed Identity).

---

## Verification Checkpoint

- [ ] Each specialist agent file created in `my-app/backend/app/agents/`
- [ ] `workflow.py` wires all agents into HandoffBuilder
- [ ] TRIAGE_INSTRUCTIONS has explicit routing categories for each agent
- [ ] Each of your test queries routes to the expected agent (verified via `handoff` SSE event)
- [ ] Backend starts cleanly with no import errors

---

## Next: [Module 05 — Build Your MCP Server](./05-rag-search.md)
        for idx, row in hist.iterrows()
    ]
```

Then restart the server and verify the tool appears in `tools/list`.

## Exercise 2: Connect the new tool to an agent

In `backend/app/agents/private_data.py`, the Yahoo Finance MCP tool is already wired up.
After adding the new tool, ask the agent: "Show me AAPL price history for the last 3 months".

## Key Code References
- [mcp-servers/yahoo-finance/server.py](../../mcp-servers/yahoo-finance/server.py)
- [mcp-servers/portfolio-db/server.py](../../mcp-servers/portfolio-db/server.py)
- [backend/app/agents/private_data.py](../../backend/app/agents/private_data.py)

## Next: [Module 05 — RAG with AI Search](./05-rag-search.md)
