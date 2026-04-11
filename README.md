# Portfolio Advisory Platform
## Multi-Agent Orchestration with Microsoft Foundry

A production-grade reference architecture for building **multi-agent AI workflows** using
[Microsoft Agent Framework](https://github.com/microsoft/agent-framework) and [Azure Foundry Agent Service](https://learn.microsoft.com/en-us/azure/foundry/agents/overview). Designed for the
**Capital Markets** domain — Portfolio Advisory.

---

## Architecture Overview

```
         User (React SPA + Entra Auth)
                     |
            FastAPI Backend (Python)
                     |
         ┌───────────────────────────┐
         │   Orchestrator (Handoff)  │  ← Hosted Agent, HandoffBuilder
         │   FoundryChatClient       │    Routes by intent
         └─────┬──────┬──────┬──────┘
               |      |      |      \
    Market  Portfolio  Economic  PrivateData
    Intel   Data       (FRED)    (Yahoo MCP)
   (Bing)  (Fabric)   Agent       Agent
   Agent    Agent   (ExtMCP)    (PrivMCP)
```

### Agents

| Agent | Type | Tool | Pattern |
|---|---|---|---|
| `orchestrator` | Hosted Agent | HandoffBuilder | Routes by intent, trust |
| `market_intel` | Prompt Agent | Bing Grounding | Public market news/analysis |
| `portfolio_data` | Prompt Agent | Fabric Data Agent / SQL | Private portfolio positions |
| `economic_data` | Prompt Agent | FRED MCP (external) | Macro economic indicators |
| `private_data` | Hosted Agent | Yahoo Finance MCP (private) | Real-time quotes |

### Core Framework Features Used

1. **[Handoff Orchestration](https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows/orchestrations/handoff_simple.py)** — Intent-based routing with trust enforcement
2. **[Concurrent Orchestration](https://github.com/microsoft/agent-framework/tree/main/python/samples/03-workflows/orchestrations/concurrent_agents.py)** — Parallel data aggregation
3. **[Context Compaction](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/compaction)** — Long conversation management
4. **[AI Search Context Provider](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search)** — RAG over research documents
5. **[CosmosDB History Provider](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/conversations/cosmos_history_provider.py)** — Durable conversation sessions
6. **[Observability](https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/observability)** — Azure Monitor + OpenTelemetry
7. **[A2A Protocol](https://github.com/microsoft/agent-framework/tree/main/python/samples/04-hosting/a2a)** — Cross-service agent communication

---

## Getting Started

### Prerequisites

- Azure CLI + `az login`
- Azure Developer CLI (`azd`)
- Python 3.11+
- Node.js 20+
- Docker Desktop

### Quick Deploy (one command)

```bash
azd up
```

This provisions all infrastructure and deploys all services.

### Manual Local Setup

```bash
# 1. Clone and configure
cp backend/.env.example backend/.env
# Edit backend/.env with your values

# 2. Install Python dependencies
cd backend && pip install -r requirements.txt

# 3. Start MCP servers
cd ../mcp-servers/yahoo-finance && pip install -r requirements.txt && python server.py &
cd ../mcp-servers/portfolio-db && pip install -r requirements.txt && python server.py &

# 4. Start backend
cd ../../backend && uvicorn app.main:app --reload

# 5. Start frontend
cd ../frontend && npm install && npm run dev
```

---

## Project Structure

```
portfolio-advisor/
├── azure.yaml                    # azd configuration
├── infra/                        # Bicep infrastructure
│   ├── main.bicep
│   └── modules/
├── backend/                      # Python FastAPI Backend
│   ├── app/
│   │   ├── agents/              # Agent definitions
│   │   ├── workflows/           # Orchestration (Handoff, Concurrent)
│   │   ├── conversation/        # CosmosDB session management
│   │   ├── observability/       # OTel + Azure Monitor setup
│   │   └── routes/              # API endpoints
│   └── Dockerfile
├── mcp-servers/
│   ├── yahoo-finance/            # Private MCP: Yahoo Finance
│   └── portfolio-db/             # Private MCP: Portfolio database
├── frontend/                     # React SPA (Entra auth + Chat + Dashboard)
│   └── src/
├── evaluations/                  # Evaluation datasets + scripts
├── scripts/                      # Provisioning helper scripts
└── docs/
    ├── architecture/             # Architecture decision records
    ├── workshop/                 # Step-by-step workshop guide
    └── coding-prompts/           # Hackathon coding prompts
```

---

## Security Architecture

| Concern | Implementation |
|---|---|
| Service-to-service auth | Managed Identity (`DefaultAzureCredential`) |
| User authentication | Microsoft Entra ID (MSAL React) |
| Financial data isolation | Portfolio agent requires user access token (OBO flow) |
| MCP authentication | Entra Managed Identity + Key Vault secrets |
| Content safety | Foundry Guardrails: PII, indirect attacks, task adherence |
| Network | Private endpoints + VNet integration |

---

## References

- [Microsoft Agent Framework](https://github.com/microsoft/agent-framework)
- [Foundry Agent Service Overview](https://learn.microsoft.com/en-us/azure/foundry/agents/overview)
- [Orchestration Patterns](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/)
- [Guardrails Overview](https://learn.microsoft.com/en-us/azure/foundry/guardrails/guardrails-overview)
- [Tool Catalog](https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/tool-catalog)
- [Grounding with Bing](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
