# Workshop Module 08: Observability & Monitoring

## Objective

Observe your deployed application through Azure Monitor and understand what is happening
inside the agent workflow at runtime. By the end you will be able to:

- Watch live agent calls in App Insights Live Metrics
- Trace a complete request from frontend to MCP server in the distributed trace view
- Query agent behaviour patterns with KQL
- Identify latency bottlenecks and error patterns

---

## How Observability Works

The backend calls `configure_observability()` at startup
([backend/app/core/observability/setup.py](../../backend/app/core/observability/setup.py)).
This sets up:

- **OpenTelemetry** — captures spans for every agent call, tool call, and HTTP request
- **Azure Monitor exporter** — sends all spans, traces, and logs to Application Insights
- **Agent Framework instrumentation** — adds agent-name, model, token usage, routing decision
  to every span automatically

```python
from agent_framework.azure import configure_azure_monitor, enable_instrumentation

configure_azure_monitor(
    connection_string=settings.applicationinsights_connection_string,
    enable_sensitive_data=False,   # NEVER change in production
)
enable_instrumentation()
```

The `enable_sensitive_data=False` setting is a hard constraint — it prevents the content
of messages from appearing in telemetry, protecting user and customer data.

---

## Step 1 — Open Application Insights

Navigate to the Azure portal → your resource group → Application Insights resource.

### Live Metrics

1. Click **Live Metrics** in the left panel
2. Open your app in the browser (or run a test query)
3. Watch the incoming request rate, server response times, and failed request count update in real time

This view is useful for confirming the app is serving requests and for watching the impact
of load (e.g., during an evaluation run).

### Application Map

1. Click **Application Map** in the left panel
2. You should see the backend → Cosmos DB, AI Search, AI Foundry connections visualised
3. Click any dependency node to see average latency and error rate for that connection

This helps identify which downstream service is causing slowdowns.

---

## Step 2 — Trace a Single Request End-to-End

1. Click **Transaction search** → **See all data**
2. Filter by **Request** and find a recent chat request
3. Click **Show all telemetry** on the request row
4. Expand the trace — you will see a waterfall of spans:

```
POST /api/chat/message                      200ms  (FastAPI route)
  |- HandoffBuilder.run()                   195ms  (workflow entry)
       |- Triage agent call                  60ms  (GPT-4o routing)
       |- Handoff: -> market_intel_agent
       |- market_intel_agent call            120ms (Foundry Prompt Agent)
            |- Bing Grounding tool call       40ms
```

Key attributes to look for in each span:
- `agent.name` — which agent ran
- `agent.model` — which model version
- `agent.prompt_tokens` / `agent.completion_tokens` — token usage per call
- `mcp.tool_name` — which MCP tool was called
- `mcp.tool_server` — which MCP server was called

---

## Step 3 — Query Agent Behaviour with KQL

Navigate to App Insights → **Logs**. Run these queries to understand your app's behaviour:

### Agent routing distribution

```kusto
dependencies
| where name startswith "agent."
| summarize count() by tostring(customDimensions["agent.name"])
| order by count_ desc
```

### Average latency per agent

```kusto
dependencies
| where name startswith "agent."
| summarize avg(duration) by tostring(customDimensions["agent.name"])
| order by avg_duration desc
```

### Token usage over time

```kusto
dependencies
| where name startswith "agent."
| extend prompt_tokens = toint(customDimensions["agent.prompt_tokens"])
| extend completion_tokens = toint(customDimensions["agent.completion_tokens"])
| summarize
    total_prompt = sum(prompt_tokens),
    total_completion = sum(completion_tokens)
    by bin(timestamp, 1h)
| order by timestamp desc
```

### Failed requests

```kusto
requests
| where success == false
| project timestamp, name, resultCode, duration, customDimensions
| order by timestamp desc
| take 20
```

### Guardrail blocks

```kusto
traces
| where message contains "BLOCKED" or message contains "guardrail"
| project timestamp, message, severityLevel
| order by timestamp desc
| take 50
```

### Compaction events

```kusto
traces
| where message contains "compaction" or message contains "summariz"
| project timestamp, message, customDimensions
| order by timestamp desc
| take 20
```

---

## Step 4 — Identify Latency Bottlenecks

Look at the agent latency query from Step 3. Common patterns:

| Observation | Likely cause | Mitigation |
|-------------|-------------|-----------|
| One agent is 3x slower than others | That agent's tool call is slow | Check downstream dependency latency |
| Triage agent is slow | Complex routing instructions | Simplify TRIAGE_INSTRUCTIONS; use GPT-4o-mini for triage |
| All agents slow at peak | Model capacity (TPM throttling) | Increase TPM quota or add retry-with-backoff |
| Compaction events increasing | Long sessions nearing token limit | Adjust `token_budget` in BaseOrchestrator |

---

## Step 5 — Set Up Alerts (Production Readiness)

Create a basic availability alert:

1. App Insights → **Alerts** → **Create alert rule**
2. Condition: **Failed requests** > 5 in 5 minutes
3. Action group: email your team

Create a latency alert:
1. Condition: **Server response time** > 15 seconds (p95)

These two alerts cover the most critical availability and performance degradation scenarios.

---

## Step 6 — Aspire Dashboard (Local Development)

For local development, the repo includes a Docker Compose configuration for the
.NET Aspire dashboard — a local OpenTelemetry collector with a clean trace UI:

```bash
cd d:\repos\hackathon
docker compose -f docker-compose.aspire.yml up -d
```

Open [http://localhost:18888](http://localhost:18888).

Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317` in your `.env` to route
local telemetry to Aspire instead of Azure Monitor.

---

## Verification Checkpoint

- [ ] Live Metrics shows active requests when you send a chat message
- [ ] Transaction search shows a distributed trace with agent spans
- [ ] KQL query for agent routing distribution returns results
- [ ] At least one alert is configured
- [ ] You can identify which agent is slowest from KQL output

---

## Next: [Module 09 — Evaluation & Continuous Testing](./09-evaluation.md)
      - uses: actions/checkout@v4
      - run: pip install httpx
      - run: python evaluations/run-evals.py --backend-url ${{ secrets.BACKEND_URL }}
```

## Workshop Complete!

You have now:
- Deployed a multi-agent portfolio advisory system to Azure
- Explored HandoffBuilder orchestration and agent routing
- Implemented MCP servers with row-level security
- Enabled RAG with Azure AI Search
- Applied security guardrails and JWT validation
- Configured compaction for long conversations
- Run automated evaluations

## Clean Up
```bash
# Tear down all Azure resources
azd down --force --purge
```

## Resources
- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-foundry/)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Architecture README](../architecture/README.md)
