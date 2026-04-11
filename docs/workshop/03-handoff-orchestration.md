# Workshop Module 03: HandoffBuilder Orchestration

## Learning Objectives
- Understand intent-based routing with HandoffBuilder
- Configure a triage agent and specialist agents
- Test agent routing with different query types
- Inspect handoff trace events in the UI

## HandoffBuilder Pattern

HandoffBuilder creates a **stateful multi-agent workflow** where a triage agent analyses user intent and delegates to the appropriate specialist. Each agent can hand back to triage or to another agent.

```
User Query
    |
    v
Triage Agent (analyses intent)
    |
    +---> market_intel_agent  (market news, stock analysis)
    +---> portfolio_agent      (user holdings, performance)
    +---> economic_agent       (macroeconomic indicators)
    +---> private_data_agent   (real-time quotes, fundamentals)
```

### Critical Requirement
**All agents in a HandoffBuilder workflow MUST set `require_per_service_call_history_persistence=True`**.
This enables the framework to correctly maintain context across handoffs.

```python
from agent_framework import Agent
from agent_framework.orchestrations import HandoffBuilder

# CORRECT
triage = Agent(
    client=client,
    instructions="Triage agent instructions...",
    require_per_service_call_history_persistence=True,  # REQUIRED
)
specialist = Agent(
    client=client,
    instructions="Specialist instructions...",
    require_per_service_call_history_persistence=True,  # REQUIRED
)

workflow = (
    HandoffBuilder(
        name="portfolio-workflow",
        participants=[triage, specialist],
    )
    .with_start_agent(triage)
    .build()
)

# Run the workflow
result = await workflow.run("What is the Apple stock price?", session=session)
```

## Exercise 1: Test routing decisions

Send messages that should route to different specialists:

```bash
# Should route to market_intel
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What are analysts saying about Nvidia?", "session_id": "test-market"}'

# Should route to portfolio
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "Show me my current portfolio holdings", "session_id": "test-portfolio"}'

# Should route to economic
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the current inflation rate?", "session_id": "test-economic"}'
```

Inspect the SSE events in the response — you will see `type: "handoff"` events showing routing decisions.

## Exercise 2: Inspect the triage instructions

Open `backend/app/agents/market_intel.py` and find the `TRIAGE_INSTRUCTIONS` string in `portfolio_workflow.py`.
The triage agent is given explicit routing rules — this is by design. LLM-only routing without explicit rules can be non-deterministic.

**Challenge**: Add a new routing rule for "Options trading" queries and create a stub options agent.

## Exercise 3: Stream handoff traces to the UI

The React frontend `ChatPanel.tsx` already captures `type: "handoff"` SSE events and displays agent badges.
Open the browser at http://localhost:5173 and watch the agent routing in the chat UI.

## Key Code References
- [backend/app/workflows/portfolio_workflow.py](../../backend/app/workflows/portfolio_workflow.py) — HandoffBuilder + ConcurrentBuilder
- [backend/app/routes/chat.py](../../backend/app/routes/chat.py) — SSE streaming endpoint

## Next: [Module 04 — MCP Servers](./04-mcp-servers.md)
