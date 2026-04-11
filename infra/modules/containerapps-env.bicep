// ============================================================
// Container Apps Environment module
// Hosts: backend API, Yahoo Finance MCP, Portfolio DB MCP
// ============================================================

param name string
param location string
param tags object
param logAnalyticsWorkspaceId string

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: last(split(logAnalyticsWorkspaceId, '/'))
}

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
  }
}

output id string = containerAppsEnv.id
output name string = containerAppsEnv.name
