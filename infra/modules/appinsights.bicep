// ============================================================
// Application Insights + Log Analytics module
// Used by: configure_azure_monitor() in FoundryChatClient
// Reference: https://learn.microsoft.com/en-us/azure/azure-monitor/app/app-insights-overview
// ============================================================

param name string
param logAnalyticsWorkspaceName string
param location string
param tags object

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: name
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

output id string = appInsights.id
output connectionString string = appInsights.properties.ConnectionString
output logAnalyticsWorkspaceId string = logAnalytics.id
