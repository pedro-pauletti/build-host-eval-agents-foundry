// -----------------------------------------------------------------------------
// Zava Foundry Demos - main infrastructure (subscription scope)
// Provisions everything into rg-zava-demo. Deploy with azd OR:
//   az deployment sub create -l eastus2 -f infra/main.bicep \
//     -p environmentName=zava-demo location=eastus2 principalId=<your-objectId>
// -----------------------------------------------------------------------------
targetScope = 'subscription'

@minLength(1)
@description('Name of the azd environment / demo (used for tagging and tokens).')
param environmentName string = 'zava-demo'

@description('Primary Azure region for all resources.')
param location string = 'eastus2'

@description('Region for Azure AI Search (fallback region if the primary lacks capacity).')
param searchLocation string = 'eastus'

@description('Resource group to create/use.')
param resourceGroupName string = 'rg-zava-demo'

@description('Object ID of the deploying user (for data-plane RBAC). Leave empty to skip user role assignments.')
param principalId string = ''

@description('Model deployments to create on the Foundry account.')
param deployments array = [
  {
    name: 'gpt-4.1'
    model: { format: 'OpenAI', name: 'gpt-4.1', version: '2025-04-14' }
    sku: { name: 'GlobalStandard', capacity: 100 }
  }
  {
    name: 'model-router'
    model: { format: 'OpenAI', name: 'model-router', version: '2025-08-07' }
    sku: { name: 'GlobalStandard', capacity: 30 }
  }
  {
    name: 'text-embedding-3-large'
    model: { format: 'OpenAI', name: 'text-embedding-3-large', version: '1' }
    sku: { name: 'Standard', capacity: 30 }
  }
  {
    name: 'gpt-realtime-mini'
    model: { format: 'OpenAI', name: 'gpt-realtime-mini', version: '2025-10-06' }
    sku: { name: 'GlobalStandard', capacity: 1 }
  }
]

var tags = {
  'azd-env-name': environmentName
  project: 'zava-foundry-demos'
}
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
  }
}

module foundry 'modules/foundry.bicep' = {
  scope: rg
  name: 'foundry'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    deployments: deployments
  }
}

module search 'modules/search.bicep' = {
  scope: rg
  name: 'search'
  params: {
    location: searchLocation
    tags: tags
    resourceToken: resourceToken
  }
}

module containers 'modules/containers.bicep' = {
  scope: rg
  name: 'containers'
  params: {
    location: location
    tags: tags
    resourceToken: resourceToken
    logAnalyticsCustomerId: monitoring.outputs.logAnalyticsCustomerId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
  }
}

module rbac 'modules/rbac.bicep' = {
  scope: rg
  name: 'rbac'
  params: {
    searchName: search.outputs.searchName
    acrName: containers.outputs.acrName
    foundryPrincipalId: foundry.outputs.accountPrincipalId
    projectPrincipalId: foundry.outputs.projectPrincipalId
    appIdentityPrincipalId: containers.outputs.appIdentityPrincipalId
    userPrincipalId: principalId
  }
}

module connections 'modules/connections.bicep' = {
  scope: rg
  name: 'connections'
  params: {
    accountName: foundry.outputs.accountName
    projectName: foundry.outputs.projectName
    searchEndpoint: search.outputs.searchEndpoint
    searchResourceId: search.outputs.searchId
  }
}

// --- Outputs (consumed by azd env / scripts / notebooks) ---
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = subscription().tenantId

output AZURE_AI_ACCOUNT_NAME string = foundry.outputs.accountName
output AZURE_AI_PROJECT_NAME string = foundry.outputs.projectName
output AZURE_AI_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output FOUNDRY_PROJECT_ENDPOINT string = foundry.outputs.projectEndpoint
output AZURE_AI_ACCOUNT_ENDPOINT string = foundry.outputs.accountEndpoint

output AZURE_SEARCH_ENDPOINT string = search.outputs.searchEndpoint
output AZURE_SEARCH_NAME string = search.outputs.searchName
output AZURE_SEARCH_CONNECTION_NAME string = connections.outputs.connectionName
output AZURE_SEARCH_CONNECTION_ID string = connections.outputs.connectionId

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = containers.outputs.acrLoginServer
output AZURE_CONTAINER_REGISTRY_NAME string = containers.outputs.acrName
output AZURE_CONTAINER_APPS_ENVIRONMENT_ID string = containers.outputs.environmentId
output AZURE_CONTAINER_APPS_ENVIRONMENT_NAME string = containers.outputs.environmentName
output AZURE_APP_IDENTITY_ID string = containers.outputs.appIdentityId
output AZURE_APP_IDENTITY_CLIENT_ID string = containers.outputs.appIdentityClientId

output APPLICATIONINSIGHTS_CONNECTION_STRING string = monitoring.outputs.appInsightsConnectionString
output APPLICATIONINSIGHTS_NAME string = monitoring.outputs.appInsightsName
