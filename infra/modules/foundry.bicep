// Foundry account (Azure AI Services) + Foundry project + model deployments.
param location string
param tags object
param resourceToken string
param deployments array

var accountName = 'zava-foundry-${resourceToken}'
var projectName = 'zava-project'

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    // Custom subdomain is required for token-based auth and the Foundry endpoint.
    customSubDomainName: accountName
    // Enables the Foundry Agent Service project management plane.
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

@batchSize(1)
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = [
  for d in deployments: {
    parent: account
    name: d.name
    sku: {
      name: d.sku.name
      capacity: d.sku.capacity
    }
    properties: {
      model: {
        format: d.model.format
        name: d.model.name
        version: d.model.version
      }
    }
  }
]

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Zava Demo Project'
    description: 'Foundry project for the Zava agents demo (InventoryAgent + DeliverySupport).'
  }
  dependsOn: [
    modelDeployments
  ]
}

output accountName string = account.name
output accountEndpoint string = 'https://${account.name}.services.ai.azure.com/'
output accountPrincipalId string = account.identity.principalId
output projectName string = project.name
output projectPrincipalId string = project.identity.principalId
output projectEndpoint string = 'https://${account.name}.services.ai.azure.com/api/projects/${project.name}'
