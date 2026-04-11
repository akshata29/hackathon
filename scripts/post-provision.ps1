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

# ──────────────────────────────────────────────────────────────────────────────
# Entra App Registrations for OBO token flow
# Creates 3 app registrations (backend-api, portfolio-mcp, yahoo-mcp), exposes
# API scopes, rotates a client secret, writes it to Key Vault, and persists the
# app IDs into the azd environment and backend .env for local development.
# ──────────────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "--- Entra App Registrations (OBO) ---" -ForegroundColor Cyan

# Derive Key Vault name from the URI
$kvUri  = azd env get-value AZURE_KEY_VAULT_URI 2>$null
$kvName = if ($kvUri) { ($kvUri -replace 'https://', '' -replace '\.vault\.azure\.net.*', '') } else { $null }
$tenantId = azd env get-value AZURE_TENANT_ID 2>$null

function Get-OrCreateApp {
    param([string]$DisplayName)
    $apps = az ad app list --display-name $DisplayName --query "[0]" | ConvertFrom-Json
    if ($apps) {
        Write-Host "  App exists: $DisplayName ($($apps.appId))" -ForegroundColor Gray
        return $apps
    }
    Write-Host "  Creating app: $DisplayName" -ForegroundColor Yellow
    return (az ad app create --display-name $DisplayName --sign-in-audience AzureADMyOrg | ConvertFrom-Json)
}

function Add-ApiScope {
    param([string]$ObjectId, [string]$ScopeName, [string]$Description)
    $app = az rest --method GET --url "https://graph.microsoft.com/v1.0/applications/$ObjectId" | ConvertFrom-Json
    if ($app.api.oauth2PermissionScopes | Where-Object { $_.value -eq $ScopeName }) {
        Write-Host "    Scope exists: $ScopeName" -ForegroundColor Gray
        return
    }
    $newId = [System.Guid]::NewGuid().ToString()
    $existingScopes = if ($app.api.oauth2PermissionScopes) { @($app.api.oauth2PermissionScopes) } else { @() }
    $newScope = @{
        adminConsentDescription = $Description
        adminConsentDisplayName = $ScopeName
        id                      = $newId
        isEnabled               = $true
        type                    = "User"
        userConsentDescription  = $Description
        userConsentDisplayName  = $ScopeName
        value                   = $ScopeName
    }
    $patchBody = @{ api = @{ oauth2PermissionScopes = $existingScopes + $newScope } } | ConvertTo-Json -Depth 10 -Compress
    az rest --method PATCH `
        --url "https://graph.microsoft.com/v1.0/applications/$ObjectId" `
        --headers "Content-Type=application/json" `
        --body $patchBody | Out-Null
    Write-Host "    Added scope: $ScopeName" -ForegroundColor Green
}

# 1. Backend API — audience for frontend tokens; OBO exchange client
$backendApiApp   = Get-OrCreateApp -DisplayName "portfolio-advisor-backend-api"
$backendApiAppId = $backendApiApp.appId
$backendApiObjId = $backendApiApp.id
az ad app update --id $backendApiAppId --identifier-uris "api://$backendApiAppId" 2>$null | Out-Null
Add-ApiScope -ObjectId $backendApiObjId -ScopeName "Chat.Read" -Description "Read conversations on behalf of the signed-in user"

# 2. Portfolio DB MCP — audience for OBO tokens issued to portfolio-db service
$portfolioMcpApp   = Get-OrCreateApp -DisplayName "portfolio-advisor-portfolio-mcp"
$portfolioMcpAppId = $portfolioMcpApp.appId
$portfolioMcpObjId = $portfolioMcpApp.id
az ad app update --id $portfolioMcpAppId --identifier-uris "api://$portfolioMcpAppId" 2>$null | Out-Null
Add-ApiScope -ObjectId $portfolioMcpObjId -ScopeName "portfolio.read" -Description "Read portfolio holdings on behalf of the signed-in user"

# 3. Yahoo Finance MCP — audience for OBO tokens issued to yahoo-finance service
$yahooMcpApp   = Get-OrCreateApp -DisplayName "portfolio-advisor-yahoo-mcp"
$yahooMcpAppId = $yahooMcpApp.appId
$yahooMcpObjId = $yahooMcpApp.id
az ad app update --id $yahooMcpAppId --identifier-uris "api://$yahooMcpAppId" 2>$null | Out-Null
Add-ApiScope -ObjectId $yahooMcpObjId -ScopeName "market.read" -Description "Read market data on behalf of the signed-in user"

# 4. Backend client secret (for OBO exchange; stored in Key Vault)
Write-Host "  Rotating client secret for backend-api..." -ForegroundColor Yellow
$credResult    = az ad app credential reset --id $backendApiAppId --years 1 --append | ConvertFrom-Json
$clientSecret  = $credResult.password

if ($clientSecret -and $kvName) {
    az keyvault secret set `
        --vault-name $kvName `
        --name "entra-backend-client-secret" `
        --value $clientSecret | Out-Null
    Write-Host "  Secret written to KV '$kvName': entra-backend-client-secret" -ForegroundColor Green
} elseif (-not $kvName) {
    Write-Warning "AZURE_KEY_VAULT_URI not set — skipping KV secret write."
}

# 5. Persist app IDs into azd env (picked up on next azd up / azd deploy)
azd env set ENTRA_BACKEND_CLIENT_ID $backendApiAppId
azd env set PORTFOLIO_MCP_CLIENT_ID $portfolioMcpAppId
azd env set YAHOO_MCP_CLIENT_ID     $yahooMcpAppId

# 6. Append Entra vars to backend .env for local development
$secretNote = if ($clientSecret) { $clientSecret } else { "# retrieve from Key Vault: entra-backend-client-secret" }
$entraBlock = @"

# Entra OBO -- generated by post-provision.ps1
# Do NOT commit ENTRA_CLIENT_SECRET to source control
ENTRA_TENANT_ID=$tenantId
ENTRA_BACKEND_CLIENT_ID=$backendApiAppId
PORTFOLIO_MCP_CLIENT_ID=$portfolioMcpAppId
YAHOO_MCP_CLIENT_ID=$yahooMcpAppId
ENTRA_CLIENT_SECRET=$secretNote
"@
Add-Content -Path $envFile -Value $entraBlock
Write-Host "  Entra vars appended: $envFile" -ForegroundColor Green

Write-Host ""
Write-Host "IMPORTANT: run 'azd deploy' to propagate app IDs to Container Apps." -ForegroundColor Yellow
Write-Host ""
