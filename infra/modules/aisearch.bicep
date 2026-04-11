// ============================================================
// Azure AI Search module
// Used by: AzureAISearchContextProvider for RAG over research docs
// Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/context_providers/azure_ai_search
// Index: portfolio-research (investment research, regulatory docs, market reports)
// ============================================================

param name string
param location string
param tags object
param managedIdentityPrincipalId string

// Search Index Data Contributor role
var searchIndexDataContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
)
// Search Service Contributor role
var searchServiceContributorRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
)

resource searchService 'Microsoft.Search/searchServices@2024-03-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    publicNetworkAccess: 'enabled'
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http403'
      }
    }
    semanticSearch: 'standard'
  }
}

// Grant managed identity data access
resource searchDataContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, managedIdentityPrincipalId, searchIndexDataContributorRole)
  scope: searchService
  properties: {
    roleDefinitionId: searchIndexDataContributorRole
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource searchServiceContributorAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(searchService.id, managedIdentityPrincipalId, searchServiceContributorRole)
  scope: searchService
  properties: {
    roleDefinitionId: searchServiceContributorRole
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output id string = searchService.id
output endpoint string = 'https://${searchService.name}.search.windows.net'
output name string = searchService.name
