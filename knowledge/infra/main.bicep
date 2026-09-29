// Knowledge base for the voice agent demos: one Azure AI Search service (keyword + semantic
// ranker, key auth disabled) holding the synthetic service-desk corpus. Every example app reads
// it through the shared search_knowledge_base tool with its managed identity (Search Index Data
// Reader, granted by the app's shared-access module when AZURE_SEARCH_SERVICE_NAME is set).
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

@metadata({
  azd: {
    type: 'location'
  }
})
param location string = 'centralus'

param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

@allowed([
  'basic'
  'standard'
])
@description('basic is the smallest tier with the semantic ranker and Microsoft Entra ID data-plane auth for this demo.')
param searchSku string = 'basic'

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module search 'modules/search.bicep' = {
  name: 'search-${uniqueString(subscription().id, environmentName, location)}'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    searchSku: searchSku
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output KNOWLEDGE_RESOURCE_GROUP string = rg.name
output AZURE_SEARCH_SERVICE_NAME string = search.outputs.SEARCH_SERVICE_NAME
output AZURE_SEARCH_ENDPOINT string = search.outputs.SEARCH_ENDPOINT
output AZURE_SEARCH_INDEX string = 'knowledge'
output AZURE_SEARCH_SEMANTIC_CONFIG string = 'default'
