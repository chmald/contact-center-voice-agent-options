param environmentName string
param location string
param principalId string

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string
param searchSku string
param tags object

var searchName = 'srch-${uniqueString(subscription().id, environmentName, location)}'
var searchServiceContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchIndexDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var developerRoles = [
  searchServiceContributorRoleId
  searchIndexDataContributorRoleId
]

resource search 'Microsoft.Search/searchServices@2023-11-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: searchSku
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: true
    semanticSearch: 'free'
  }
}

// The deploying user creates the index and uploads the synthetic documents (postprovision hook).
resource developerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in developerRoles: if (!empty(principalId)) {
  name: guid(search.id, principalId, roleId)
  scope: search
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: principalType
  }
}]

output SEARCH_SERVICE_NAME string = search.name
output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
