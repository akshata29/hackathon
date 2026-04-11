// ============================================================
// Azure Static Web App module — React frontend
// Integrated with Entra authentication via SWA built-in auth
// Reference: https://learn.microsoft.com/en-us/azure/static-web-apps/authentication-authorization
// ============================================================

param name string
param location string
param tags object
param backendUrl string

resource staticWebApp 'Microsoft.Web/staticSites@2023-01-01' = {
  name: name
  location: location
  tags: union(tags, { 'azd-service-name': 'frontend' })
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    buildProperties: {
      skipGithubActionWorkflowGeneration: true
    }
    enterpriseGradeCdnStatus: 'Disabled'
  }
}

// Link backend API as a linked backend for SWA
resource linkedBackend 'Microsoft.Web/staticSites/linkedBackends@2023-01-01' = {
  name: 'backend'
  parent: staticWebApp
  properties: {
    backendResourceId: backendUrl
    region: location
  }
}

output url string = 'https://${staticWebApp.properties.defaultHostname}'
output name string = staticWebApp.name
output id string = staticWebApp.id
