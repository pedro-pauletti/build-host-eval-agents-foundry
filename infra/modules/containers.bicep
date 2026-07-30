// Azure Container Registry + Container Apps managed environment + app identity.
param location string
param tags object
param resourceToken string
param logAnalyticsCustomerId string
param logAnalyticsWorkspaceId string

// User-assigned identity used by the Zava container apps (ACR pull, Foundry calls).
resource appIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-zava-apps-${resourceToken}'
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'acrzava${resourceToken}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    adminUserEnabled: true
  }
}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: last(split(logAnalyticsWorkspaceId, '/'))
}

resource containerEnv 'Microsoft.App/managedEnvironments@2024-10-02-preview' = {
  name: 'cae-zava-${resourceToken}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsCustomerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output environmentId string = containerEnv.id
output environmentName string = containerEnv.name
output appIdentityId string = appIdentity.id
output appIdentityClientId string = appIdentity.properties.clientId
output appIdentityPrincipalId string = appIdentity.properties.principalId
