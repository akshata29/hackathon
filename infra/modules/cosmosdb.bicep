// ============================================================
// Azure Cosmos DB module
// Used by: CosmosHistoryProvider for conversation persistence
// Schema: conversations container, partitioned by session_id
// Reference: https://github.com/microsoft/agent-framework/tree/main/python/samples/02-agents/conversations
// Best Practice: Use serverless for dev; provisioned throughput for prod
// ============================================================

param accountName string
param location string
param tags object
param managedIdentityPrincipalId string

var databaseName = 'portfolio-advisor'
var conversationsContainer = 'conversations'
var checkpointsContainer = 'workflow-checkpoints'

// Cosmos DB Built-in Data Contributor role
var cosmosDataContributorRole = subscriptionResourceId(
  'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions',
  '00000000-0000-0000-0000-000000000002'
)

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: accountName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    // Use Entra ID (no keys exposed to applications)
    disableLocalAuth: false
    enableAutomaticFailover: false
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    backupPolicy: {
      type: 'Continuous'
      continuousModeProperties: {
        tier: 'Continuous7Days'
      }
    }
  }
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  name: databaseName
  parent: cosmosAccount
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// Conversations container — partitioned by session_id
// Used by CosmosHistoryProvider from agent_framework.azure
resource conversationsContainerRes 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: conversationsContainer
  parent: database
  properties: {
    resource: {
      id: conversationsContainer
      partitionKey: {
        paths: ['/session_id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
      }
      defaultTtl: 2592000 // 30 days
    }
  }
}

// Workflow checkpoints container — CosmosCheckpointStorage
resource checkpointsContainerRes 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: checkpointsContainer
  parent: database
  properties: {
    resource: {
      id: checkpointsContainer
      partitionKey: {
        paths: ['/workflow_id']
        kind: 'Hash'
        version: 2
      }
      defaultTtl: 86400 // 24 hours
    }
  }
}

// Chat sessions container — per-user conversation history for the UI
// Partitioned by user_id for efficient per-user queries
var sessionsContainer = 'chat-sessions'

resource sessionsContainerRes 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  name: sessionsContainer
  parent: database
  properties: {
    resource: {
      id: sessionsContainer
      partitionKey: {
        paths: ['/user_id']
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          { path: '/*' }
        ]
      }
      defaultTtl: 7776000 // 90 days
    }
  }
}

// Grant Managed Identity data access via RBAC (no connection strings)
resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  name: guid(cosmosAccount.id, managedIdentityPrincipalId, cosmosDataContributorRole)
  parent: cosmosAccount
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: managedIdentityPrincipalId
    scope: cosmosAccount.id
  }
}

output endpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = databaseName
output id string = cosmosAccount.id
