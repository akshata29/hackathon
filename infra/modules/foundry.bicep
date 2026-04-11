// ============================================================
// Azure AI Foundry Hub + Project module
// Provisions: Hub, Project, GPT-4o deployment
// Also configures: AI Search connection, Application Insights connection
// Reference: https://learn.microsoft.com/en-us/azure/ai-foundry/how-to/create-azure-ai-resource
// IMPORTANT: Foundry Agent Service requires Agent Service API (V2) endpoint format:
//   https://<resource>.services.ai.azure.com/api/projects/<project>
// ============================================================

param hubName string
param projectName string
param location string
param tags object
param managedIdentityId string
param managedIdentityPrincipalId string
param appInsightsId string
param aiSearchId string
param modelName string
param modelVersion string
param modelCapacity int

// Azure AI Account (Hub)
resource hub 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: hubName
  location: location
  tags: tags
  kind: 'AIServices'
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: hubName
    publicNetworkAccess: 'Enabled'
    apiProperties: {}
  }
}

// GPT-4o deployment under the Hub
resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  name: modelName
  parent: hub
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

// text-embedding-3-small — required for vector search in the portfolio-research index
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = {
  name: 'text-embedding-3-small'
  parent: hub
  dependsOn: [modelDeployment]
  sku: {
    name: 'Standard'
    capacity: 120
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
  }
}

// Foundry Project (scoped to Hub)
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = {
  name: projectName
  parent: hub
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    description: 'Portfolio Advisor multi-agent project'
  }
}

// Cognitive Services OpenAI Contributor for managed identity
var cogServicesContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'a001fd3d-188f-4b5d-821b-7da978bf7442'
)

resource managedIdentityFoundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hub.id, managedIdentityPrincipalId, cogServicesContributorRole)
  scope: hub
  properties: {
    roleDefinitionId: cogServicesContributorRole
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Project endpoint in Agent Service V2 format
// Format: https://<resource>.services.ai.azure.com/api/projects/<project>
var projectEndpoint = 'https://${hub.name}.services.ai.azure.com/api/projects/${project.name}'

output hubId string = hub.id
output projectId string = project.id
output projectEndpoint string = projectEndpoint
output hubEndpoint string = hub.properties.endpoint
