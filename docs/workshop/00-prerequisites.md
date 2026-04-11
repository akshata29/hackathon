# Workshop Module 00: Prerequisites

## Learning Objectives

By the end of this workshop you will have:
- Deployed a full multi-agent portfolio advisory system to Azure
- Understood HandoffBuilder and ConcurrentBuilder orchestration patterns
- Implemented RAG, compaction, observability, and security guardrails
- Extended the system with your own MCP server

## Time Estimate

Full workshop: ~4 hours (8 modules x ~30 min each)

## Prerequisites

### Azure
- Azure subscription with Owner or Contributor role
- Quota for `gpt-4o` (GlobalStandard, 50k TPM) in your preferred region
  - Check: [Azure AI Foundry quota page](https://ai.azure.com/resource/quota)
  - Recommended regions: East US 2, West US 3, Sweden Central

### Local Tools
- [Azure Developer CLI (azd)](https://aka.ms/azd) v1.9+: `winget install Microsoft.Azd`
- [Azure CLI](https://docs.microsoft.com/cli/azure/install) v2.55+: `winget install Microsoft.AzureCLI`
- Python 3.11+: `winget install Python.Python.3.11`
- Node.js 20+: `winget install OpenJS.NodeJS.LTS`
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for local MCP testing)
- VS Code with Python, Bicep, and GitHub Copilot extensions

### Clone the Repository
```bash
git clone https://github.com/your-org/portfolio-advisor
cd portfolio-advisor
```

### Authenticate
```bash
az login
azd auth login
```

## Verify Setup
```bash
az account show --query "{name:name, id:id}" -o table
azd version
python --version
node --version
```

Expected outputs:
```
Python 3.11.x
v20.x.x
```

## Next: [Module 01 — Deploy Infrastructure](./01-infrastructure.md)
