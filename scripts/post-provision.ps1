# post-provision.ps1
# azd post-provision hook — runs after `azd up` provisions Azure resources
# Seeds the AI Search index and outputs environment configuration

param()

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Portfolio Advisor: Post-Provision Setup ===" -ForegroundColor Cyan

# Retrieve azd environment values
$foundryEndpoint   = azd env get-value FOUNDRY_PROJECT_ENDPOINT   2>$null
$searchEndpoint    = azd env get-value AZURE_SEARCH_ENDPOINT       2>$null
$searchIndex       = azd env get-value AZURE_SEARCH_INDEX          2>$null
$cosmosEndpoint    = azd env get-value AZURE_COSMOS_ENDPOINT        2>$null
$backendUrl        = azd env get-value BACKEND_API_URL              2>$null

if (-not $searchIndex) { $searchIndex = "portfolio-research" }

# Write backend .env for local development
$envContent = @"
FOUNDRY_PROJECT_ENDPOINT=$foundryEndpoint
FOUNDRY_MODEL=gpt-4o
AZURE_COSMOS_ENDPOINT=$cosmosEndpoint
AZURE_COSMOS_DATABASE=portfolio-advisor
CONVERSATIONS_CONTAINER=conversations
AZURE_SEARCH_ENDPOINT=$searchEndpoint
AZURE_SEARCH_INDEX=$searchIndex
YAHOO_MCP_URL=http://localhost:8001/mcp
PORTFOLIO_MCP_URL=http://localhost:8002/mcp
LOG_LEVEL=INFO
ENABLE_SENSITIVE_DATA=false
"@

$envFile = Join-Path $PSScriptRoot ".." "backend" ".env"
$envContent | Set-Content -Path $envFile -Encoding UTF8
Write-Host "  Written: $envFile" -ForegroundColor Green

# Seed AI Search index
Write-Host ""
Write-Host "Seeding AI Search index '$searchIndex'..." -ForegroundColor Yellow
$seedScript = Join-Path $PSScriptRoot "seed-search-index.py"
$env:AZURE_SEARCH_ENDPOINT = $searchEndpoint
$env:AZURE_SEARCH_INDEX    = $searchIndex

python $seedScript
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Search index seeding failed (exit code $LASTEXITCODE). You can run it manually: python scripts/seed-search-index.py"
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Backend API: $backendUrl"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. cd frontend && npm install && npm run dev"
Write-Host "  2. cd backend && uvicorn app.main:app --reload"
Write-Host "  3. Visit http://localhost:5173"
Write-Host ""
