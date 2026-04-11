# Workshop Module 02: Microsoft Agent Framework

## Learning Objectives
- Understand `FoundryChatClient` vs `FoundryAgent`
- Create your first agent with tools
- Use `CosmosHistoryProvider` for conversation persistence
- Enable Azure Monitor observability

## Key Concepts

### FoundryChatClient
Lightweight client backed by an Azure AI Foundry project. Used for **all workflow orchestration** (HandoffBuilder, ConcurrentBuilder). Does NOT require pre-deployed server-side agent resources in the Foundry portal.

```python
from agent_framework.foundry import FoundryChatClient
from azure.identity import DefaultAzureCredential

client = FoundryChatClient(
    project_endpoint="https://<hub>.services.ai.azure.com/api/projects/<project>",
    model="gpt-4o",
    credential=DefaultAzureCredential(),
)
```

### FoundryAgent
Connects to a **pre-deployed Prompt Agent** in the Foundry portal (configured with tools, grounding, etc. via the UI). Use this when you want to reference a portal-configured agent from code.

```python
from agent_framework.foundry import FoundryAgent

agent = FoundryAgent(
    project_endpoint="...",
    agent_name="my-portal-agent",
    credential=DefaultAzureCredential(),
)
```

### Agent with context providers
```python
from agent_framework import Agent
from agent_framework.azure import CosmosHistoryProvider

async with CosmosHistoryProvider(
    endpoint=cosmos_endpoint,
    database_name="portfolio-advisor",
    container_name="conversations",
    credential=DefaultAzureCredential(),
) as history_provider:
    async with Agent(
        client=client,
        instructions="You are a helpful financial advisor.",
        context_providers=[history_provider],
    ) as agent:
        session = agent.create_session(session_id="user123:conv456")
        result = await agent.run("How is my portfolio doing?", session=session)
        print(result.content)
```

## Exercise 1: Run the agent locally

1. Install dependencies:
```bash
cd backend
pip install -r requirements.txt
```

2. Copy environment file:
```bash
cp .env.example .env
# Fill in FOUNDRY_PROJECT_ENDPOINT and other values from azd env get-values
```

3. Start the backend:
```bash
uvicorn app.main:app --reload
```

4. Test the health endpoint:
```bash
curl http://localhost:8000/health
```

5. Send a chat message:
```bash
curl -X POST http://localhost:8000/api/chat/message \
  -H "Content-Type: application/json" \
  -d '{"message": "What is the outlook for technology stocks?", "session_id": "test-001"}'
```

## Exercise 2: Add Azure Monitor observability

Open `backend/app/observability/setup.py` and review how `configure_azure_monitor()` is called. Note:
- `enable_sensitive_data=False` — NEVER change this in production
- `enable_instrumentation()` activates agent-framework telemetry
- Token usage, agent routing decisions, and tool calls all appear in App Insights

View traces: Navigate to your App Insights resource → Live Metrics or Application Map.

## Key Code References
- [backend/app/agents/market_intel.py](../../backend/app/agents/market_intel.py) — market intelligence agent
- [backend/app/observability/setup.py](../../backend/app/observability/setup.py) — observability setup
- [backend/app/conversation/session_manager.py](../../backend/app/conversation/session_manager.py) — Cosmos session management

## Next: [Module 03 — HandoffBuilder Orchestration](./03-handoff-orchestration.md)
