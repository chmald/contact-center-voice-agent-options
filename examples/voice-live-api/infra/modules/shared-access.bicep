// Grants an example app's managed identity access to resources in the shared platform
// resource group (single Foundry endpoint, knowledge index, ACS) and returns their endpoints.
// Deployed into the shared resource group; every input is optional.
param foundryName string = ''
param foundryRoleIds array = []
param searchServiceName string = ''
param acsResourceName string = ''
param principalId string

var searchIndexDataReaderRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '1407120a-92aa-4202-b7e9-c0e197c71c8f')
// ACS Call Automation with Microsoft Entra ID (managed identity) is authorized through
// the Contributor role on the Communication Services resource only.
var contributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: empty(foundryName) ? 'unused' : foundryName
}

resource search 'Microsoft.Search/searchServices@2023-11-01' existing = {
  name: empty(searchServiceName) ? 'unused' : searchServiceName
}

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' existing = {
  name: empty(acsResourceName) ? 'unused' : acsResourceName
}

resource foundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in foundryRoleIds: if (!empty(foundryName)) {
  name: guid(foundry.id, principalId, roleId)
  scope: foundry
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource searchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(searchServiceName)) {
  name: guid(search.id, principalId, searchIndexDataReaderRoleId)
  scope: search
  properties: {
    roleDefinitionId: searchIndexDataReaderRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource acsAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(acsResourceName)) {
  name: guid(acs.id, principalId, contributorRoleId)
  scope: acs
  properties: {
    roleDefinitionId: contributorRoleId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

output foundryCustomSubDomain string = empty(foundryName) ? '' : foundry.properties.customSubDomainName
output searchEndpoint string = empty(searchServiceName) ? '' : 'https://${searchServiceName}.search.windows.net'
output acsEndpoint string = empty(acsResourceName) ? '' : 'https://${acs.properties.hostName}'
