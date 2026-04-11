// ============================================================
// Key Vault Secrets module
// Stores API keys for external MCP servers
// These are placeholder values — replace after provisioning
// ============================================================

param keyVaultName string
param mcpYahooApiKeyPlaceholder string
param mcpFredApiKeyPlaceholder string

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
