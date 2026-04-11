// ============================================================
// Container Apps module — Backend API + MCP Servers
// All containers use User-Assigned Managed Identity (no secrets in env)
// Reference: https://learn.microsoft.com/en-us/azure/container-apps/managed-identity
// ============================================================

param environmentId string
param registryLoginServer string
param managedIdentityId string
param managedIdentityClientId string
param location string
param tags object
param resourceToken string

// Environment variable values (non-secret)
param keyVaultUri string
param cosmosEndpoint string
param cosmosDatabaseName string
param aiSearchEndpoint string
param appInsightsConnectionString string
param foundryProjectEndpoint string
param foundryModelName string

var backendAppName = 'ca-backend-${resourceToken}'
var yahooMcpAppName = 'ca-mcp-yahoo-${resourceToken}'
var portfolioMcpAppName = 'ca-mcp-portfolio-${resourceToken}'

// ──────────────────────────────────────────────────
// Yahoo Finance MCP Server
// ──────────────────────────────────────────────────
resource yahooMcpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: yahooMcpAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'mcp-yahoo-finance' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8001
        transport: 'http'
      }
      registries: [
        {
          server: registryLoginServer
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-yahoo'
          image: '${registryLoginServer}/mcp-yahoo-finance:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'KEYVAULT_URI'
              value: keyVaultUri
            }
            {
              name: 'YAHOO_API_KEY_SECRET_NAME'
              value: 'yahoo-finance-api-key'
            }
            {
              name: 'MCP_AUTH_ENABLED'
              value: 'true'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 5
      }
    }
  }
}

// ──────────────────────────────────────────────────
// Portfolio DB MCP Server
// ──────────────────────────────────────────────────
resource portfolioMcpApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: portfolioMcpAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'mcp-portfolio-db' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: false
        targetPort: 8002
        transport: 'http'
      }
      registries: [
        {
          server: registryLoginServer
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'mcp-portfolio'
          image: '${registryLoginServer}/mcp-portfolio-db:latest'
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

// ──────────────────────────────────────────────────
// Backend FastAPI
// ──────────────────────────────────────────────────
resource backendApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: backendAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'backend' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentityId}': {}
    }
  }
  properties: {
    environmentId: environmentId
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        corsPolicy: {
          allowedOrigins: ['*']
          allowedMethods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS']
          allowedHeaders: ['*']
          allowCredentials: false
        }
      }
      registries: [
        {
          server: registryLoginServer
          identity: managedIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'backend'
          image: '${registryLoginServer}/portfolio-advisor-backend:latest'
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentityClientId
            }
            {
              name: 'FOUNDRY_PROJECT_ENDPOINT'
              value: foundryProjectEndpoint
            }
            {
              name: 'FOUNDRY_MODEL'
              value: foundryModelName
            }
            {
              name: 'AZURE_COSMOS_ENDPOINT'
              value: cosmosEndpoint
            }
            {
              name: 'AZURE_COSMOS_DATABASE_NAME'
              value: cosmosDatabaseName
            }
            {
              name: 'AZURE_COSMOS_CONTAINER_NAME'
              value: 'conversations'
            }
            {
              name: 'AZURE_SEARCH_ENDPOINT'
              value: aiSearchEndpoint
            }
            {
              name: 'AZURE_SEARCH_INDEX_NAME'
              value: 'portfolio-research'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
            {
              name: 'ENABLE_INSTRUMENTATION'
              value: 'true'
            }
            {
              name: 'YAHOO_MCP_URL'
              value: 'https://${yahooMcpApp.properties.configuration.ingress.fqdn}'
            }
            {
              name: 'PORTFOLIO_MCP_URL'
              value: 'https://${portfolioMcpApp.properties.configuration.ingress.fqdn}'
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
        rules: [
          {
            name: 'http-scale'
            http: {
              metadata: {
                concurrentRequests: '100'
              }
            }
          }
        ]
      }
    }
  }
}

output backendUrl string = 'https://${backendApp.properties.configuration.ingress.fqdn}'
output yahooMcpUrl string = 'https://${yahooMcpApp.properties.configuration.ingress.fqdn}'
output portfolioMcpUrl string = 'https://${portfolioMcpApp.properties.configuration.ingress.fqdn}'
