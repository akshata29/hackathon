# Workshop Module 00: Prerequisites & Setup

## What You Will Build

In this workshop you will build a **production-grade, multi-agent AI application** from
scratch — starting from a clean template, guided by AI coding prompts at each step.
By the end you will have:

- Deployed the complete Azure infrastructure (AI Foundry, Cosmos DB, AI Search, Container Apps, and more) using a single `azd up` command
- Implemented multi-agent orchestration using Microsoft Agent Framework and Azure AI Foundry
- Built a private MCP data server with row-level security for your confidential data
- Added RAG-powered context retrieval via Azure AI Search
- Secured the app with Entra ID authentication and input/output guardrails
- Shipped a React SPA frontend with streaming agent responses
- Validated the implementation with an automated evaluation harness
- Monitored agent behaviour end-to-end in Azure Monitor

The **reference implementation** is a Portfolio Advisory Platform — a multi-agent system
that routes investor queries to specialist agents for market intelligence, portfolio analysis,
economic data, and real-time quotes. You will run this reference to understand the end state,
then use the clean template to build your **own domain-specific application**.

---

## Workshop Map

| Module | Topic | Time |
|--------|-------|------|
| 00 | Prerequisites & Setup (this module) | 20 min |
| 01 | Deploy the Infrastructure | 30 min |
| 02 | Explore the Reference Implementation | 30 min |
| 03 | Define Your Use-Case & Configure | 20 min |
| 04 | Build Specialist Agents & Workflow | 45 min |
| 05 | Build Your MCP Server | 30 min |
| 06 | RAG, Domain Data & Frontend | 30 min |
| 07 | Security, Guardrails & Deployment | 25 min |
| 08 | Observability & Monitoring | 20 min |
| 09 | Evaluation & Continuous Testing | 30 min |

**Total estimated time**: ~5 hours. Each module ends with a verification checkpoint.
Work at your own pace — modules 03 onward are independent once the infrastructure is up.

---

## Prerequisites

### Azure Subscription

- Azure subscription with **Owner** or **Contributor** role
- Quota approved for `gpt-4o` (GlobalStandard, 50k TPM) in your target region
  - Check quota: [ai.azure.com/resource/quota](https://ai.azure.com/resource/quota)
  - Recommended regions: **East US 2**, **West US 3**, **Sweden Central**
  - Requesting quota typically resolves in under 5 minutes in a supported region

### Local Tools (install before the workshop)

```powershell
# Azure Developer CLI (azd) — infrastructure + deploy automation
winget install Microsoft.Azd

# Azure CLI — resource querying and scripting
winget install Microsoft.AzureCLI

# Python 3.11 — backend runtime
winget install Python.Python.3.11

# Node.js 20 LTS — frontend build tooling
winget install OpenJS.NodeJS.LTS

# Docker Desktop — local MCP server containers
# Download from: https://www.docker.com/products/docker-desktop/
```

### VS Code Extensions

- **Python** (`ms-python.python`) — backend development
- **Bicep** (`ms-azuretools.vscode-bicep`) — infrastructure editing
- **GitHub Copilot + Copilot Chat** — AI-assisted coding (agent mode required for workshop prompts)
- **Azure Tools** (`ms-vscode.vscode-node-azure-pack`) — Azure resource exploration

---

## Step 1 — Clone the Repository

```bash
git clone https://github.com/your-org/multi-agent-template
cd multi-agent-template
```

---

## Step 2 — Authenticate with Azure

```bash
# Azure CLI — for direct Azure resource operations
az login

# Azure Developer CLI — for azd provision and deploy
azd auth login
```

Verify authentication and confirm the correct subscription:

```bash
az account show --query "{name:name, subscriptionId:id, tenantId:tenantId}" -o table
```

If you need to switch subscriptions:

```bash
az account set --subscription "<subscription-name-or-id>"
az account show --query "name" -o tsv   # confirm
```

---

## Step 3 — Understand the Project Layout

Spend 5 minutes understanding the structure before writing any code:

```
multi-agent-template/
  backend/           <- Reference implementation (Portfolio Advisor backend)
  frontend/          <- Reference React SPA
  mcp-servers/       <- Reference MCP servers (yahoo-finance, portfolio-db)
  infra/             <- Bicep IaC — all Azure resources (shared)
  scripts/           <- Post-provision seeding scripts (shared)
  evaluations/       <- Evaluation harness + test datasets (shared)
  template/          <- CLEAN SCAFFOLD — your starting point
    backend/
    frontend/
    mcp-servers/
    docs/
      coding-prompts/    <- AI coding prompts for each build step
  docs/
    architecture/        <- Architecture decisions (ADRs)
    coding-prompts/      <- Extended prompts for the reference app
    workshop/            <- This workshop guide (you are here)
```

**Key distinction**:
- `backend/`, `frontend/`, `mcp-servers/` — the **reference implementation**.
  Study this to understand the target architecture.
- `template/` — your **clean starting point**.
  Build your own application here, guided by the prompts in `template/docs/coding-prompts/`.
- `infra/`, `scripts/`, `evaluations/` — **shared infrastructure** that both the reference and
  your new app use without modification.

---

## Step 4 — Set Up the Python Environment

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cd ..
```

---

## Verification Checkpoint

```bash
az account show --query "name" -o tsv
azd version
python --version
node --version
docker --version
```

Expected output:

```
<your subscription name>
azd version 1.x.x (x.y.z)
Python 3.11.x
v20.x.x
Docker version 27.x.x
```

If any command fails, resolve it before moving on. Blocked tools will stall later modules.

---

## Next: [Module 01 — Deploy the Infrastructure](./01-infrastructure.md)
