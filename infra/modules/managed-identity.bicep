// ============================================================
// Managed Identity module
// Best Practice: Use User-Assigned Managed Identity for all services
// so identity can be pre-assigned before containers start.
// Reference: https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/
// ============================================================

param name string
param location string
param tags object

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
  tags: tags
}

output id string = managedIdentity.id
output clientId string = managedIdentity.properties.clientId
output principalId string = managedIdentity.properties.principalId
