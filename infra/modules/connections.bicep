// Foundry project connection to Azure AI Search (keyless / AAD via project MI).
// Backs the Foundry IQ knowledge base + the agent's Azure AI Search tool.
param accountName string
param projectName string
param searchEndpoint string
param searchResourceId string

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' existing = {
  parent: account
  name: projectName
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'zava-search'
  properties: {
    category: 'CognitiveSearch'
    target: searchEndpoint
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: searchResourceId
    }
  }
}

output connectionName string = searchConnection.name
output connectionId string = searchConnection.id
