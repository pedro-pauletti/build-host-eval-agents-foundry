// Data-plane RBAC: grant Foundry/project managed identities and app identity access
// to Azure AI Search and ACR. Uses keyless (managed identity) auth where possible.
param searchName string
param acrName string
param foundryPrincipalId string
param projectPrincipalId string
param appIdentityPrincipalId string
@description('Deploying user object ID; empty to skip user role assignments.')
param userPrincipalId string = ''

// Built-in role definition IDs
var searchIndexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var searchServiceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
var searchIndexDataReader = '1407120a-92aa-4202-b7e9-c0e197c71c8f'
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' existing = {
  name: searchName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

// --- Foundry project MI: read/write Zava index (Foundry IQ / AI Search tool) ---
resource projectSearchDataContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, projectPrincipalId, searchIndexDataContributor)
  properties: {
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
  }
}

resource projectSearchServiceContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, projectPrincipalId, searchServiceContributor)
  properties: {
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
  }
}

// --- Foundry account MI: same search access (some flows use the account identity) ---
resource accountSearchDataContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, foundryPrincipalId, searchIndexDataContributor)
  properties: {
    principalId: foundryPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
  }
}

// --- App identity: pull images from ACR + read the search index ---
resource appAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, appIdentityPrincipalId, acrPull)
  properties: {
    principalId: appIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

resource appSearchReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, appIdentityPrincipalId, searchIndexDataReader)
  properties: {
    principalId: appIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataReader)
  }
}

// --- Deploying user: index data (for scripts/index_docs) + manage service ---
resource userSearchDataContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  scope: search
  name: guid(search.id, userPrincipalId, searchIndexDataContributor)
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchIndexDataContributor)
  }
}

resource userSearchServiceContrib 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(userPrincipalId)) {
  scope: search
  name: guid(search.id, userPrincipalId, searchServiceContributor)
  properties: {
    principalId: userPrincipalId
    principalType: 'User'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', searchServiceContributor)
  }
}
