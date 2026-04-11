# Workshop Module 01: Deploy Infrastructure

## Objective

Provision all Azure resources using `azd up` — a single command that runs Bicep templates and post-provision hooks.

## Steps

### 1. Initialise azd environment
```bash
azd env new dev
```

### 2. Set required parameters
```bash
azd env set AZURE_LOCATION eastus2
# Optional: set a custom prefix for resource names
# azd env set RESOURCE_TOKEN myteam
```

### 3. Provision and deploy
```bash
azd up
```

This single command:
1. Runs `infra/main.bicep` to create all Azure resources
2. Builds Docker images for backend, yahoo-mcp, portfolio-mcp
3. Pushes images to Azure Container Registry
4. Deploys to Container Apps and Static Web App
5. Runs `scripts/post-provision.ps1` which seeds the AI Search index

> Expected time: 8-12 minutes

### 4. Verify deployment
```bash
# Check outputs
azd env get-values

# Test backend health
BACKEND_URL=$(azd env get-value BACKEND_API_URL)
curl $BACKEND_URL/health
```

Expected:
```json
{"status": "healthy", "version": "0.1.0", "foundry_endpoint": "https://..."}
```

### 5. Open the frontend
```bash
FRONTEND_URL=$(azd env get-value FRONTEND_URL)
echo $FRONTEND_URL
```

Navigate to the URL in your browser.

## What Was Created

| Resource | SKU | Purpose |
|---------|-----|---------|
| AI Foundry Hub + Project | — | GPT-4o deployment + project endpoint |
| GPT-4o deployment | GlobalStandard 50k TPM | Language model for all agents |
| Container Apps Environment | Consumption | Hosts backend + MCP servers |
| Container Registry | Basic | Docker images |
| Cosmos DB | Serverless | Conversation history |
| AI Search | Standard | RAG knowledge base |
| Key Vault | Standard | Secrets (RBAC mode) |
| App Insights | — | Observability |
| Static Web App | Standard | React frontend |

## Cost Estimate (Dev Environment)

~$5-15/day in active use. Run `azd down` when done to stop billing.

## Next: [Module 02 — Explore Agent Framework](./02-agent-framework.md)
