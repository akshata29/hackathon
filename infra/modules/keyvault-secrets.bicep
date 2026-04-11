// ============================================================
// Key Vault Secrets module
// Stores API keys for external MCP servers and OBO client secret
// These are placeholder values — replace after provisioning
// ============================================================

param keyVaultName string
param mcpYahooApiKeyPlaceholder string
param mcpFredApiKeyPlaceholder string
// Placeholder for the backend app registration client secret used for OBO exchange.
// After 'azd up', replace this value by running scripts/post-provision.ps1 which
// creates the app registrations and writes the real secret.
param entraBackendClientSecretPlaceholder string = 'REPLACE_WITH_BACKEND_CLIENT_SECRET'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource yahooApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'yahoo-finance-api-key'
  parent: keyVault
  properties: {
    value: mcpYahooApiKeyPlaceholder
    attributes: {
      enabled: true
    }
  }
}

resource fredApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'fred-api-key'
  parent: keyVault
  properties: {
    value: mcpFredApiKeyPlaceholder
    attributes: {
      enabled: true
    }
  }
}

resource entraClientSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'entra-backend-client-secret'
  parent: keyVault
  properties: {
    value: entraBackendClientSecretPlaceholder
    attributes: {
      enabled: true
    }
  }
}

output entraClientSecretUri string = entraClientSecret.properties.secretUri

    attributes: {
      enabled: true
    }
  }
}
