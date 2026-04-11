# Hackathon Coding Prompts — Multi-Agent Portfolio Advisor

These prompts are designed to help hackathon teams implement specific components of the
multi-agent orchestration system using AI coding assistants (GitHub Copilot, Cursor, etc.).

---

## Prompt 1: Add a New Specialist Agent

> **Goal**: Add a new `risk_assessment` agent to the HandoffBuilder workflow that analyses portfolio risk metrics.

```
I am building a multi-agent portfolio advisory system using Microsoft Agent Framework v1.0.0.

I need to add a new specialist agent called `risk_assessment_agent` that:
1. Analyses portfolio volatility, beta, Sharpe ratio, and maximum drawdown
2. Identifies over-concentrated positions (>10% single stock weight)
3. Suggests risk mitigation strategies
4. Is accessible via the HandoffBuilder triage agent when the user asks about risk

The project uses:
- `agent_framework.FoundryChatClient` for the LLM client
- `agent_framework.Agent` for creating agents
- `agent_framework.orchestrations.HandoffBuilder` for routing
- All agents MUST set `require_per_service_call_history_persistence=True`

The new agent should be added to `backend/app/agents/` as `risk_assessment.py`
and wired into `backend/app/workflows/portfolio_workflow.py`.

Follow the same pattern as `backend/app/agents/economic_data.py` for the file structure.
```

---

## Prompt 2: Add a New MCP Tool

> **Goal**: Add a `get_dividend_history` tool to the Yahoo Finance MCP server.

```
I have a FastMCP server at `mcp-servers/yahoo-finance/server.py` that provides
financial data tools using the `yfinance` library.

Add a new tool `get_dividend_history` that:
1. Accepts a `symbol` parameter (stock ticker)
2. Accepts an optional `years` parameter (1-5, default 3)
3. Returns a list of dicts with {ex_date, amount, dividend_type}
4. Handles errors gracefully with a {symbol, error} return on failure
5. Uses yfinance's `ticker.dividends` or `ticker.actions` to fetch dividend data

Follow the same pattern as the existing `get_quote` tool in the file.
Include a complete docstring that will be displayed to the AI agent as the tool description.
```

---

## Prompt 3: Implement WebSocket Reconnection in the Frontend

> **Goal**: Make the React chat panel resilient to WebSocket disconnections.

```
I have a React chat component at `frontend/src/components/ChatPanel.tsx` that
connects to a WebSocket endpoint at `/api/chat/ws/{session_id}`.

Currently it opens a WebSocket once on mount. I need to add:
1. Automatic reconnection with exponential backoff (1s, 2s, 4s, max 30s)
2. Maximum retry count of 5 before showing a "Connection failed" error
3. A connection status indicator (connected/reconnecting/failed) shown in the UI
4. Ability to switch between SSE mode (POST /api/chat/message) and WebSocket mode
   based on a `connectionMode` prop

The component uses React hooks (useState, useEffect, useRef) and TypeScript.
Do not use any external WebSocket libraries — use the native browser WebSocket API.
```

---

## Prompt 4: Add Streaming to ConcurrentBuilder (Comprehensive Mode)

> **Goal**: Stream partial results from ConcurrentBuilder as each specialist agent completes.

```
I have a PortfolioOrchestrator class in `backend/app/workflows/portfolio_workflow.py`
that uses `ConcurrentBuilder` from `agent_framework.orchestrations` to run 4 agents
in parallel.

Currently `run_comprehensive()` is an async generator that yields events.
I need to modify it so that as each individual parallel agent completes, it yields
a partial result event immediately rather than waiting for all agents to finish.

The event format should be:
  {"type": "partial_result", "agent": "<agent_name>", "content": "<agent_response>"}

When all agents are done, a synthesis agent aggregates the results and a final
  {"type": "synthesis", "agent": "synthesis", "content": "<final_answer>"}
event is emitted.

Use asyncio.as_completed or agent-framework's native event streaming if available.
```

---

## Prompt 5: Add a Recharts Line Chart for Portfolio Performance

> **Goal**: Add a portfolio performance history chart to the Dashboard.

```
I have a React Dashboard component at `frontend/src/components/Dashboard.tsx`
that displays portfolio holdings using Recharts.

Add a new `PerformanceChart` component in `frontend/src/components/PerformanceChart.tsx` that:
1. Fetches 12 months of monthly portfolio return data from `GET /api/portfolio/performance`
2. Displays a Recharts `LineChart` with:
   - Portfolio return (blue line, label "My Portfolio")
   - S&P 500 benchmark (gray line, label "S&P 500")
   - X axis: month labels (Jan, Feb, ... Dec)
   - Y axis: return % with a "%" suffix
   - Tooltip showing both values on hover
   - A horizontal reference line at 0%
3. Shows a loading skeleton (gray animated div) while data is loading
4. Shows an error state if the API call fails

Use Tailwind CSS for styling, TypeScript, and React hooks.
Import the component into Dashboard.tsx above the holdings table.
```

---

## Prompt 6: Add Azure Content Safety to Guardrails

> **Goal**: Integrate Azure Content Safety API for post-generation response checking.

```
I have a guardrails module at `backend/app/guardrails/policy.py` with a
`check_agent_response()` function that currently does regex-based PII detection.

Enhance it to also call the Azure Content Safety API using the
`azure-ai-contentsafety` SDK when `AZURE_CONTENT_SAFETY_ENDPOINT` is configured:

1. Install: `azure-ai-contentsafety>=1.0.0` (add to `backend/requirements.txt`)
2. Use `ContentSafetyClient` with `DefaultAzureCredential()`
3. Call `analyze_text()` with categories: [Hate, Violence, SelfHarm, Sexual]
4. Block responses where any category severity >= 2
5. Cache the client instance (no new client per call)
6. If `AZURE_CONTENT_SAFETY_ENDPOINT` is not set, fall back to the existing regex-only check
7. Log blocked content at WARNING level without including the blocked text itself

Make the function async to support the async Azure SDK.
```

---

## Prompt 7: Create a Bicep Module for Azure Content Safety

> **Goal**: Add Azure Content Safety as an optional infrastructure module.

```
I have Bicep infrastructure at `infra/modules/` for a portfolio advisory platform.
The existing modules follow this pattern (see `infra/modules/appinsights.bicep` for reference):
- Module-scoped params for naming and location
- Tags propagation
- Outputs for endpoint and resource ID

Create a new module `infra/modules/contentsafety.bicep` that:
1. Provisions a `Microsoft.CognitiveServices/accounts` resource of kind `ContentSafety`
2. Uses `S0` SKU
3. Assigns the managed identity the `Cognitive Services User` role
   (role definition ID: `a97b65f3-24c7-4388-baec-2e87135dc908`)
4. Outputs: `endpoint`, `resourceId`, `name`

Then add it as an optional module in `infra/main.bicep` with a `deployContentSafety` bool param
(default false) so teams can opt in.
```

---

## Prompt 8: Implement Agent Tracing UI

> **Goal**: Add an expandable "Agent Trace" panel below each chat response.

```
In `frontend/src/components/ChatPanel.tsx`, each assistant message in the
`messages` state has an optional `traces: HandoffTrace[]` array
(defined in `frontend/src/types.ts`) that records agent routing decisions.

Add an expandable trace panel below assistant messages:
1. When `traces.length > 0`, show a small "View trace" toggle button below the message
2. Clicking it expands a panel showing:
   - A visual chain: [AgentBadge from] → [AgentBadge to] for each trace entry
   - Total latency if available (from a `latency_ms` field in events)
3. Use a CSS transition for smooth expand/collapse
4. The `AgentBadge` component is already available at `frontend/src/components/AgentBadge.tsx`
5. Use TypeScript, React hooks, and Tailwind CSS only (no additional libraries)
```

---

## Prompt 9: Add Locust Load Tests

> **Goal**: Create a Locust load test file for the chat API.

```
I have a FastAPI backend with endpoints:
- POST /api/chat/message — accepts {"message": str, "session_id": str, "mode": str}
  returns SSE stream
- GET /api/portfolio/holdings — returns portfolio holdings JSON
- GET /health — returns health check JSON

Create `locustfile.py` in the project root for load testing with Locust:
1. Define a `PortfolioAdvisorUser` class
2. Tasks with weights:
   - health_check (weight 1): GET /health
   - get_holdings (weight 2): GET /api/portfolio/holdings
   - send_chat_message (weight 5): POST /api/chat/message with a random question
     from a list of 10 test questions; consume the SSE stream to completion
3. Wait time: between 1 and 5 seconds between tasks
4. On_start: generate a unique session_id per user
5. Use the requests library (Locust's built-in), handle SSE by iterating response.iter_lines()

The locustfile should work with the existing VS Code task that runs:
  locust -f locustfile.py -u 10 -r 2 --run-time 1m
```

---

## Tips for Using These Prompts

1. **Provide file context**: Always attach the relevant existing file(s) as context when using these prompts with Copilot/Cursor.

2. **Iterate**: Start with the prompt as-is, then follow up with "Now add error handling for X" or "Make it work with the existing Y function".

3. **Test immediately**: After each implementation, run the relevant test or curl command from the workshop guide to verify.

4. **Ask for explanations**: Add "Explain each step as comments" to any prompt for a more educational output.
