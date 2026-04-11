// ============================================================
// Azure Key Vault module
// Stores: Yahoo Finance API key, FRED API key, and other secrets
// Best Practice: Use RBAC (not Access Policies) for Key Vault access
// Reference: https://learn.microsoft.com/en-us/azure/key-vault/general/rbac-guide
// ============================================================

param name string
param location string
param tags object
param managedIdentityPrincipalId string
param principalId string

// Key Vault Secrets User role
var keyVaultSecretsUserRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)
// Key Vault Administrator role (for provisioning principal)
var keyVaultAdminRole = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '00482a5a-887f-4fb3-b363-3b7fe8e74483'
)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
      bypass: 'AzureServices'
    }
  }
}

// Managed Identity gets read access to secrets
resource managedIdentitySecretsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentityPrincipalId, keyVaultSecretsUserRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRole
    principalId: managedIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Provisioning principal gets admin access to set secrets
resource principalAdminAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(principalId)) {
  name: guid(keyVault.id, principalId, keyVaultAdminRole)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultAdminRole
    principalId: principalId
    principalType: 'User'
  }
}

output name string = keyVault.name
output id string = keyVault.id
output uri string = keyVault.properties.vaultUri
