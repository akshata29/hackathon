// ============================================================
// Azure Container Registry module
// Used by: azd to push backend and MCP server Docker images
// Best Practice: Use Managed Identity for pull access (no admin credentials)
// ============================================================

param name string
param location string
param tags object
param managedIdentityPrincipalId string

// AcrPull role
var acrPullRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7f951dda-4ed3-4680-a7ca-43fe172d538d'
)

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-01-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
  }
}

// Allow managed identity to pull images
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(containerRegistry.id, managedIdentityPrincipalId, acrPullRole)
  scope: containerRegistry
  properties: {
    roleDefinitionId: acrPullRole
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output loginServer string = containerRegistry.properties.loginServer
output name string = containerRegistry.name
output id string = containerRegistry.id
