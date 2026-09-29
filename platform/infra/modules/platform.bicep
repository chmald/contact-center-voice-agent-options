param environmentName string
param location string
param principalId string

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string

@allowed([
  'gpt-realtime-2.1-mini'
  'gpt-realtime-mini'
])
param realtimeModel string

param realtimeModelVersion string
param realtimeDeploymentCapacity int
param deploySearch bool
param deployCommunicationServices bool
param communicationDataLocation string
param projectName string = 'voice-agents'
param tags object

var suffix = uniqueString(subscription().id, environmentName, location)
var foundryName = 'ais-${suffix}'
var searchName = 'srch-${suffix}'
var acsName = 'acs-${suffix}'
var modelVersions = {
  'gpt-realtime-2.1-mini': '2026-07-07'
  'gpt-realtime-mini': '2025-12-15'
}
var resolvedModelVersion = empty(realtimeModelVersion) ? modelVersions[realtimeModel] : realtimeModelVersion
var openAIUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var cognitiveServicesUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'a97b65f3-24c7-4388-baec-2e87135dc908')
var foundryUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '53ca6127-db72-4b80-b1b0-d745d6d5456d')
var searchServiceContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7ca78c08-252a-4471-8644-bb5ff32d4ba0')
var searchIndexDataContributorRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '8ebe5a00-799e-43f5-93ac-243d3dce84a7')
var developerFoundryRoles = [
  openAIUserRoleId
  cognitiveServicesUserRoleId
  foundryUserRoleId
]
var developerSearchRoles = [
  searchServiceContributorRoleId
  searchIndexDataContributorRoleId
]

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  // Project management + identity let the same endpoint host a Foundry project for the voice agent.
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: foundryName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    allowProjectManagement: true
  }
}

// Holds the Foundry voice agent (preview) so all three examples run on this one endpoint.
resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: projectName
    description: 'Voice comparison demo: Foundry voice agent project.'
  }
}

// The single realtime deployment both apps' Realtime API traffic uses. Voice Live's
// managed gpt-realtime-mini runs on the same resource without a deployment.
resource realtimeDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: realtimeModel
  sku: {
    name: 'GlobalStandard'
    capacity: realtimeDeploymentCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: realtimeModel
      version: resolvedModelVersion
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

// Keyword + semantic ranking (free tier of the semantic ranker) - no embedding deployment,
// so RAG adds no model quota to the shared AI endpoint.
resource search 'Microsoft.Search/searchServices@2023-11-01' = if (deploySearch) {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'basic'
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

resource acs 'Microsoft.Communication/communicationServices@2023-04-01' = if (deployCommunicationServices) {
  name: acsName
  location: 'global'
  tags: tags
  properties: {
    dataLocation: communicationDataLocation
  }
}

resource developerFoundryAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in developerFoundryRoles: if (!empty(principalId)) {
  name: guid(foundry.id, principalId, roleId)
  scope: foundry
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: principalType
  }
}]

// Lets the deploying user create the index and upload documents (scripts/load-knowledge-index.py).
resource developerSearchAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for roleId in developerSearchRoles: if (deploySearch && !empty(principalId)) {
  name: guid(resourceGroup().id, searchName, principalId, roleId)
  scope: search
  properties: {
    roleDefinitionId: roleId
    principalId: principalId
    principalType: principalType
  }
}]

output FOUNDRY_NAME string = foundry.name
output FOUNDRY_PROJECT_NAME string = project.name
output FOUNDRY_PROJECT_ENDPOINT string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com/api/projects/${project.name}'
output VOICE_LIVE_ENDPOINT string = 'https://${foundry.properties.customSubDomainName}.services.ai.azure.com'
output OPENAI_ENDPOINT string = 'https://${foundry.properties.customSubDomainName}.openai.azure.com'
output REALTIME_DEPLOYMENT string = realtimeDeployment.name
output REALTIME_MODEL_VERSION string = resolvedModelVersion
output SEARCH_SERVICE_NAME string = deploySearch ? searchName : ''
output SEARCH_ENDPOINT string = deploySearch ? 'https://${searchName}.search.windows.net' : ''
output ACS_NAME string = deployCommunicationServices ? acsName : ''
output ACS_ENDPOINT string = deployCommunicationServices ? 'https://${acs!.properties.hostName}' : ''
