// Azure AI Search - backs the Foundry IQ knowledge base for Zava docs.
param location string
param tags object
param resourceToken string

@description('Search SKU. basic is enough for the demo; standard for more scale.')
param sku string = 'basic'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: 'srch-zava-${resourceToken}'
  location: location
  tags: tags
  sku: { name: sku }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'free'
    publicNetworkAccess: 'enabled'
    // Allow both AAD (recommended) and API-key auth for demo flexibility.
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: {
        aadAuthFailureMode: 'http401WithBearerChallenge'
      }
    }
  }
}

output searchName string = search.name
output searchEndpoint string = 'https://${search.name}.search.windows.net'
output searchId string = search.id
