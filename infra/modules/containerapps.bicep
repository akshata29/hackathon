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

// Entra ID / OBO configuration
// These are set post-provisioning by scripts/post-provision.ps1 which creates
// the three app registrations (frontend, backend-api, portfolio-mcp, yahoo-mcp).
param entraTenantId string = ''
param entraBackendClientId string = ''
param portfolioMcpClientId string = ''
param yahooMcpClientId string = ''
// Key Vault URI for the backend client secret (used for OBO exchange)
@secure()
param entraClientSecretKvUri string = ''

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
            // Entra JWT validation — validates OBO tokens from the backend
            {
              name: 'ENTRA_TENANT_ID'
              value: entraTenantId
            }
            {
              name: 'MCP_CLIENT_ID'
              value: yahooMcpClientId
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
            // Entra JWT validation — validates OBO tokens from the backend
            {
              name: 'ENTRA_TENANT_ID'
              value: entraTenantId
            }
            {
              name: 'MCP_CLIENT_ID'
              value: portfolioMcpClientId
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
        // CORS is handled by FastAPI CORSMiddleware with specific allowed origins.
        // Do not set a wildcard corsPolicy here — it would conflict with allow_credentials=true.
      }
      registries: [
        {
          server: registryLoginServer
          identity: managedIdentityId
        }
      ]
      secrets: entraClientSecretKvUri != '' ? [
        {
          name: 'entra-backend-client-secret'
          keyVaultUrl: entraClientSecretKvUri
          identity: managedIdentityId
        }
      ] : []
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
            // Entra ID: backend API app registration (JWT audience + OBO client)
            {
              name: 'ENTRA_TENANT_ID'
              value: entraTenantId
            }
            {
              name: 'ENTRA_BACKEND_CLIENT_ID'
              value: entraBackendClientId
            }
            // OBO: client secret read from Key Vault via Container Apps secret ref
            {
              name: 'ENTRA_CLIENT_SECRET'
              secretRef: 'entra-backend-client-secret'
            }
            // MCP app registration IDs (audience for OBO-issued tokens)
            {
              name: 'PORTFOLIO_MCP_CLIENT_ID'
              value: portfolioMcpClientId
            }
            {
              name: 'YAHOO_MCP_CLIENT_ID'
              value: yahooMcpClientId
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

// ──────────────────────────────────────────────────
// EasyAuth — Container Apps built-in token validation
// Defense-in-depth: validates Entra tokens at the
// platform layer before requests reach app code.
// Conditionally enabled when entraTenantId is provided.
// ──────────────────────────────────────────────────

// Yahoo Finance MCP — strict (internal service, always requires valid token)
resource yahooMcpEasyAuth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (entraTenantId != '' && yahooMcpClientId != '') {
  parent: yahooMcpApp
  name: 'current'
  properties: {
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
          clientId: yahooMcpClientId
        }
        validation: {
          allowedAudiences: [
            'api://${yahooMcpClientId}'
          ]
        }
      }
    }
    platform: {
      enabled: true
    }
  }
}

// Portfolio DB MCP — strict (internal service, always requires valid token)
resource portfolioMcpEasyAuth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (entraTenantId != '' && portfolioMcpClientId != '') {
  parent: portfolioMcpApp
  name: 'current'
  properties: {
    globalValidation: {
      unauthenticatedClientAction: 'Return401'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
          clientId: portfolioMcpClientId
        }
        validation: {
          allowedAudiences: [
            'api://${portfolioMcpClientId}'
          ]
        }
      }
    }
    platform: {
      enabled: true
    }
  }
}

// Backend API — permissive (AllowAnonymous) so the GitHub OAuth callback
// redirect (no Bearer token) is not blocked by the platform layer.
// The FastAPI Entra middleware still enforces auth on all API routes.
resource backendEasyAuth 'Microsoft.App/containerApps/authConfigs@2024-03-01' = if (entraTenantId != '' && entraBackendClientId != '') {
  parent: backendApp
  name: 'current'
  properties: {
    globalValidation: {
      unauthenticatedClientAction: 'AllowAnonymous'
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        registration: {
          openIdIssuer: '${environment().authentication.loginEndpoint}${entraTenantId}/v2.0'
          clientId: entraBackendClientId
        }
        validation: {
          allowedAudiences: [
            'api://${entraBackendClientId}'
          ]
        }
      }
    }
    platform: {
      enabled: true
    }
  }
}
