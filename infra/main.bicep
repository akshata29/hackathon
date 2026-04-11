// ============================================================
// Main Bicep entry point for Portfolio Advisor Multi-Agent Platform
// References:
//   https://learn.microsoft.com/en-us/azure/developer/azure-developer-cli/bicep
//   https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/create-azure-ai-resource
// ============================================================

targetScope = 'subscription'

// --------------- Parameters ---------------

@minLength(1)
@maxLength(64)
@description('Name of the environment (dev, staging, prod)')
param environmentName string

@minLength(1)
@description('Primary Azure region for all resources')
param location string

@description('Azure AD tenant ID for Entra authentication')
param tenantId string = subscription().tenantId

@description('Object ID of the user/service principal for role assignments during provisioning')
param principalId string = ''

@description('Model deployment name for GPT-4o in Foundry')
param foundryModelName string = 'gpt-4o'

@description('Model version')
param foundryModelVersion string = '2024-11-20'

@description('Capacity units for model deployment')
param foundryModelCapacity int = 50

@description('Entra app registration client ID for the backend API (JWT audience + OBO client)')
param entraBackendClientId string = ''

@description('Entra app registration client ID for the Portfolio MCP server')
param portfolioMcpClientId string = ''

@description('Entra app registration client ID for the Yahoo Finance MCP server')
param yahooMcpClientId string = ''

// --------------- Variables ---------------

var abbrs = loadJsonContent('./abbreviations.json')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var tags = {
  'azd-env-name': environmentName
  'project': 'portfolio-advisor'
  'managed-by': 'azd'
}

// --------------- Resource Group ---------------

resource rg 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: '${abbrs.resourcesResourceGroups}${environmentName}'
  location: location
  tags: tags
}

// --------------- Child Modules ---------------

module managedIdentity './modules/managed-identity.bicep' = {
  name: 'managed-identity'
  scope: rg
  params: {
    name: '${abbrs.managedIdentityUserAssignedIdentities}${resourceToken}'
    location: location
    tags: tags
  }
}

module keyVault './modules/keyvault.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    name: '${abbrs.keyVaultVaults}${resourceToken}'
    location: location
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    principalId: principalId
  }
}

module appInsights './modules/appinsights.bicep' = {
  name: 'appinsights'
  scope: rg
  params: {
    name: '${abbrs.insightsComponents}${resourceToken}'
    logAnalyticsWorkspaceName: '${abbrs.operationalInsightsWorkspaces}${resourceToken}'
    location: location
    tags: tags
  }
}

module cosmosDb './modules/cosmosdb.bicep' = {
  name: 'cosmosdb'
  scope: rg
  params: {
    accountName: '${abbrs.documentDBDatabaseAccounts}${resourceToken}'
    location: location
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
  }
}

module aiSearch './modules/aisearch.bicep' = {
  name: 'aisearch'
  scope: rg
  params: {
    name: '${abbrs.searchSearchServices}${resourceToken}'
    location: location
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
  }
}

module containerRegistry './modules/containerregistry.bicep' = {
  name: 'containerregistry'
  scope: rg
  params: {
    name: '${abbrs.containerRegistryRegistries}${resourceToken}'
    location: location
    tags: tags
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
  }
}

module containerAppsEnv './modules/containerapps-env.bicep' = {
  name: 'containerapps-env'
  scope: rg
  params: {
    name: '${abbrs.appManagedEnvironments}${resourceToken}'
    location: location
    tags: tags
    logAnalyticsWorkspaceId: appInsights.outputs.logAnalyticsWorkspaceId
  }
}

module foundry './modules/foundry.bicep' = {
  name: 'foundry'
  scope: rg
  params: {
    hubName: '${abbrs.cognitiveServicesAccounts}hub-${resourceToken}'
    projectName: '${abbrs.cognitiveServicesAccounts}proj-${resourceToken}'
    location: location
    tags: tags
    managedIdentityId: managedIdentity.outputs.id
    managedIdentityPrincipalId: managedIdentity.outputs.principalId
    appInsightsId: appInsights.outputs.id
    aiSearchId: aiSearch.outputs.id
    modelName: foundryModelName
    modelVersion: foundryModelVersion
    modelCapacity: foundryModelCapacity
  }
}

module containerApps './modules/containerapps.bicep' = {
  name: 'containerapps'
  scope: rg
  params: {
    environmentId: containerAppsEnv.outputs.id
    registryLoginServer: containerRegistry.outputs.loginServer
    managedIdentityId: managedIdentity.outputs.id
    managedIdentityClientId: managedIdentity.outputs.clientId
    location: location
    tags: tags
    resourceToken: resourceToken
    keyVaultUri: keyVault.outputs.uri
    cosmosEndpoint: cosmosDb.outputs.endpoint
    cosmosDatabaseName: cosmosDb.outputs.databaseName
    aiSearchEndpoint: aiSearch.outputs.endpoint
    appInsightsConnectionString: appInsights.outputs.connectionString
    foundryProjectEndpoint: foundry.outputs.projectEndpoint
    foundryModelName: foundryModelName
    entraTenantId: tenantId
    entraBackendClientId: entraBackendClientId
    portfolioMcpClientId: portfolioMcpClientId
    yahooMcpClientId: yahooMcpClientId
    entraClientSecretKvUri: kvSecrets.outputs.entraClientSecretUri
  }
}

module staticWebApp './modules/staticwebapp.bicep' = {
  name: 'staticwebapp'
  scope: rg
  params: {
    name: '${abbrs.webStaticSites}${resourceToken}'
    location: location
    tags: tags
    backendUrl: containerApps.outputs.backendUrl
  }
}

// Key Vault secrets
module kvSecrets './modules/keyvault-secrets.bicep' = {
  name: 'kv-secrets'
  scope: rg
  dependsOn: [keyVault]
  params: {
    keyVaultName: keyVault.outputs.name
    mcpYahooApiKeyPlaceholder: 'REPLACE_WITH_YAHOO_MCP_KEY'
    mcpFredApiKeyPlaceholder: 'REPLACE_WITH_FRED_API_KEY'
    entraBackendClientSecretPlaceholder: 'REPLACE_WITH_ENTRA_CLIENT_SECRET'
  }
}

// --------------- Outputs (used by azd) ---------------

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_MANAGED_IDENTITY_CLIENT_ID string = managedIdentity.outputs.clientId

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containerRegistry.outputs.loginServer
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = containerAppsEnv.outputs.id

output AZURE_COSMOS_ENDPOINT string = cosmosDb.outputs.endpoint
output AZURE_COSMOS_DATABASE_NAME string = cosmosDb.outputs.databaseName
output AZURE_COSMOS_CONTAINER_NAME string = 'conversations'

output AZURE_SEARCH_ENDPOINT string = aiSearch.outputs.endpoint
output AZURE_SEARCH_INDEX_NAME string = 'portfolio-research'

output AZURE_KEY_VAULT_URI string = keyVault.outputs.uri

output APPLICATIONINSIGHTS_CONNECTION_STRING string = appInsights.outputs.connectionString

output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_MODEL string = foundryModelName

output BACKEND_API_URL string = containerApps.outputs.backendUrl
output FRONTEND_URL string = staticWebApp.outputs.url

output ENTRA_BACKEND_CLIENT_ID string = entraBackendClientId
output PORTFOLIO_MCP_CLIENT_ID string = portfolioMcpClientId
output YAHOO_MCP_CLIENT_ID string = yahooMcpClientId
