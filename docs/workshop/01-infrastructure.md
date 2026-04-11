# Workshop Module 01: Deploy the Infrastructure

## Objective

Deploy all Azure resources for the workshop using `azd up`. This module walks through
**what the Bicep templates create**, **why each resource exists**, and **how to verify the deployment**.

By the end both the reference Portfolio Advisor and your new application will share
the same Azure infrastructure.

---

## What Gets Created

All infrastructure is defined in `infra/main.bicep` and the modules it references.
Here is a complete inventory:

| Resource | SKU / Tier | Bicep module | Purpose |
|----------|-----------|--------------|---------|
| Resource Group | — | main.bicep | Logical container for all resources |
| User-Assigned Managed Identity | — | managed-identity.bicep | No stored credentials; used by all services |
| Key Vault (RBAC mode) | Standard | keyvault.bicep | Secrets storage; no access policies |
| Log Analytics Workspace | PerGB2018 | appinsights.bicep | Log sink for App Insights |
| Application Insights | — | appinsights.bicep | Traces, metrics, distributed telemetry |
| Container Registry | Basic | containerregistry.bicep | Docker images for backend + MCP servers |
| Cosmos DB Account + DB | Serverless | cosmosdb.bicep | Conversation history + workflow checkpoints |
| AI Search | Standard | aisearch.bicep | RAG index for domain knowledge documents |
| Container Apps Environment | Consumption | containerapps-env.bicep | Shared runtime for all containers |
| Container App — backend | 0.5 vCPU / 1 GB | containerapps.bicep | FastAPI backend service (external ingress) |
| Container App — yahoo-mcp | 0.25 vCPU / 0.5 GB | containerapps.bicep | Yahoo Finance MCP server (internal only) |
| Container App — portfolio-mcp | 0.25 vCPU / 0.5 GB | containerapps.bicep | Portfolio DB MCP server (internal only) |
| AI Foundry Hub + Project | — | foundry.bicep | GPT-4o model deployment; agent endpoints |
| GPT-4o deployment | GlobalStandard 50k TPM | foundry.bicep | Language model for all agents |
| Static Web App | Standard | staticwebapp.bicep | React frontend with Entra SSO |

**Security note**: The Managed Identity is assigned RBAC roles on every downstream service.
No connection strings or API keys are stored in Container Apps environment variables.

---

## Step 1 — Initialise the azd Environment

An azd environment holds your deployment configuration (location, resource names, secrets).

```bash
cd d:\repos\hackathon

azd env new dev
```

This creates a `.azure/dev/` directory. You can have multiple environments (dev, staging, prod).

---

## Step 2 — Set Required Parameters

```bash
# Target Azure region — must have GPT-4o GlobalStandard quota
azd env set AZURE_LOCATION eastus2

# Optional: set a short prefix to avoid naming conflicts in shared subscriptions
# azd env set RESOURCE_TOKEN myteam
```

Confirm the settings:

```bash
azd env get-values
```

---

## Step 3 — Provision and Deploy

```bash
azd up
```

This single command executes in four phases:

1. **Provision** — runs `infra/main.bicep` to create all Azure resources
2. **Build** — builds Docker images for `backend`, `yahoo-mcp`, `portfolio-mcp`
3. **Push** — pushes images to the Azure Container Registry
4. **Deploy** — deploys containers to Container Apps and the SPA to Static Web App
5. **Post-provision hook** — runs `scripts/post-provision.ps1` which:
   - Seeds the AI Search index with domain research documents
   - Seeds the Cosmos DB portfolio database with sample user data
   - Registers Foundry Prompt Agents (market_intel, portfolio, economic, private_data)
   - Writes all important endpoints back to azd env values

> Expected time: **10–15 minutes** on first run. Subsequent deploys are faster (skips provision
> if infrastructure hasn't changed).

Watch the output — each phase is logged. If provisioning fails partway through,
run `azd up` again; it is idempotent.

---

## Step 4 — Verify the Deployment

### Check azd outputs

```bash
azd env get-values
```

You should see values for:

```
BACKEND_API_URL=https://backend.<env>.azurecontainerapps.io
FRONTEND_URL=https://<name>.azurestaticapps.net
AZURE_COSMOS_ENDPOINT=https://<name>.documents.azure.com:443/
AZURE_SEARCH_ENDPOINT=https://<name>.search.windows.net
FOUNDRY_PROJECT_ENDPOINT=https://<hub>.services.ai.azure.com/api/projects/<project>
APPLICATIONINSIGHTS_CONNECTION_STRING=InstrumentationKey=...
```

### Health check the backend

```bash
# PowerShell
$BACKEND=(azd env get-value BACKEND_API_URL)
Invoke-RestMethod "$BACKEND/health"
```

Expected:

```json
{
  "status": "healthy",
  "version": "1.0.0",
  "foundry_endpoint": "https://..."
}
```

### Open the frontend

```bash
$FRONTEND=(azd env get-value FRONTEND_URL)
Start-Process $FRONTEND
```

Log in with your Entra credentials. The Portfolio Advisor should be fully functional.

---

## Step 5 — Explore What Was Deployed in the Portal

Navigate to the Azure portal and open the resource group `rg-portfolio-advisor-dev`.
Spend a few minutes exploring:

1. **AI Foundry Hub** — open the Foundry portal, navigate to the project, then **Agents**.
   You should see 4 Prompt Agents registered: `market-intel`, `portfolio-data`, `economic-data`, `private-data`.

2. **Cosmos DB** — open **Data Explorer**, navigate to `portfolio-advisor` > `conversations`.
   This container holds per-session agent conversation history.

3. **AI Search** — open the index `portfolio-research`.
   Click **Search explorer** and run a query like `*` to see the seeded research documents.

4. **App Insights** — open **Live Metrics** and send a chat message in the frontend.
   Watch the live request/response flow appear in real time.

5. **Container Apps** — click the `backend` app, then **Log stream** to see live logs.

---

## Step 6 — Understand the Post-Provision Scripts

The hooks in `scripts/` run automatically after `azd up` but are worth understanding:

| Script | What it does |
|--------|-------------|
| `scripts/post-provision.ps1` | Orchestrates all seeding + Foundry setup |
| `scripts/setup-foundry.py` | Registers Prompt Agents in the Foundry portal via API |
| `scripts/seed-search-index.py` | Uploads domain research documents to AI Search |
| `scripts/seed-portfolio-db.py` | Inserts sample portfolio data for test users in Cosmos DB |

To re-run any script independently:

```bash
# Re-seed the AI Search index
python scripts/seed-search-index.py

# Re-seed the portfolio database
python scripts/seed-portfolio-db.py

# Re-register Foundry Prompt Agents
python scripts/setup-foundry.py
```

---

## Cost Management

**Estimated cost**: ~$8–18/day in active use (GPT-4o token consumption is the main driver).

When not actively using the environment:

```bash
# Shut down Container Apps (stops compute billing, keeps data)
az containerapp update --name backend --resource-group rg-portfolio-advisor-dev --min-replicas 0

# OR tear down everything (recoverable via azd up)
azd down
```

---

## Verification Checkpoint

| Check | Command | Expected result |
|-------|---------|----------------|
| Backend healthy | `Invoke-RestMethod "$BACKEND/health"` | `{"status": "healthy", ...}` |
| Frontend loads | Open `$FRONTEND` in browser | Login page appears |
| Cosmos DB seeded | Azure portal > Data Explorer | Portfolio data visible |
| AI Search seeded | AI Search > Search explorer > `*` | 6+ documents returned |
| Foundry agents | Foundry portal > Agents | 4 agents registered |

All five checks must pass before moving on.

---

## Next: [Module 02 — Explore the Reference Implementation](./02-agent-framework.md)
