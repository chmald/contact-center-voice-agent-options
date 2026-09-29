targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

// Voice agents need BOTH Foundry Agent Service and Voice Live in the region (voice agents are public preview).
// Re-check before use: https://learn.microsoft.com/en-us/azure/foundry/agents/concepts/limits-quotas-regions
@allowed([
  'centralus'
  'eastus2'
  'swedencentral'
  'westus2'
])
@metadata({
  azd: {
    type: 'location'
  }
})
param location string

@description('Region for Container Apps, ACR, Log Analytics, and the app identity. Empty = same as location (the AI region). Use a nearby region when Container Apps capacity is constrained in the AI region; the extra hop adds a few ms of network latency to every audio frame.')
param appLocation string = ''

param principalId string = ''

@allowed([
  'User'
  'ServicePrincipal'
])
param principalType string = 'User'

@description('Managed Voice Live model the voice agent runs on (no deployment, no Azure OpenAI quota).')
@allowed([
  'gpt-realtime-2.1-mini'
  'gpt-realtime-mini'
  'gpt-realtime'
])
param voiceAgentModel string = 'gpt-realtime-2.1-mini'

param voiceAgentVoice string = 'en-US-Ava:DragonHDLatestNeural'

param voiceAgentName string = 'voice-agent-demo'

param voiceAgentProjectName string = 'voice-agents'

param maxConcurrentSessions int = 20

param webExists bool = false

@description('Shared mode: resource group of the platform/ azd project. Empty = standalone (own Foundry resource).')
param sharedResourceGroup string = ''
param sharedFoundryName string = ''
@description('Shared mode: Foundry project in the platform resource that holds the voice agent.')
param sharedFoundryProjectName string = ''
param searchServiceName string = ''
param searchIndexName string = 'knowledge'
param searchSemanticConfig string = 'default'
param acsResourceName string = ''
param telephonyProviders string = ''
@secure()
param telephonyWebhookSecret string = ''
@secure()
param acsEventGridSecret string = ''
@secure()
param twilioAuthToken string = ''
param telephonyOverflowNumber string = ''

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources 'modules/resources.bicep' = {
  name: 'resources-${uniqueString(subscription().id, environmentName, location)}'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    appLocation: empty(appLocation) ? location : appLocation
    principalId: principalId
    principalType: principalType
    voiceAgentModel: voiceAgentModel
    voiceAgentVoice: voiceAgentVoice
    voiceAgentName: voiceAgentName
    voiceAgentProjectName: voiceAgentProjectName
    sharedFoundryProjectName: sharedFoundryProjectName
    maxConcurrentSessions: maxConcurrentSessions
    webExists: webExists
    tags: tags
    sharedResourceGroup: sharedResourceGroup
    sharedFoundryName: sharedFoundryName
    searchServiceName: searchServiceName
    searchIndexName: searchIndexName
    searchSemanticConfig: searchSemanticConfig
    acsResourceName: acsResourceName
    telephonyProviders: telephonyProviders
    telephonyWebhookSecret: telephonyWebhookSecret
    acsEventGridSecret: acsEventGridSecret
    twilioAuthToken: twilioAuthToken
    telephonyOverflowNumber: telephonyOverflowNumber
  }
}

output AZURE_LOCATION string = location
output AZURE_APP_LOCATION string = empty(appLocation) ? location : appLocation
output AZURE_TENANT_ID string = tenant().tenantId
output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = resources.outputs.AZURE_CONTAINER_REGISTRY_ENDPOINT
output AZURE_CONTAINER_REGISTRY_NAME string = resources.outputs.AZURE_CONTAINER_REGISTRY_NAME
output SERVICE_WEB_NAME string = resources.outputs.SERVICE_WEB_NAME
output SERVICE_WEB_URI string = resources.outputs.SERVICE_WEB_URI
output VOICE_AGENT_ENDPOINT string = resources.outputs.VOICE_AGENT_ENDPOINT
output VOICE_AGENT_PROJECT string = resources.outputs.VOICE_AGENT_PROJECT
output VOICE_AGENT_PROJECT_ENDPOINT string = resources.outputs.VOICE_AGENT_PROJECT_ENDPOINT
output VOICE_AGENT_NAME string = voiceAgentName
output VOICE_AGENT_MODEL string = voiceAgentModel
output VOICE_AGENT_VOICE string = voiceAgentVoice
output VOICE_AGENT_API_VERSION string = '2026-07-15'
output FOUNDRY_RESOURCE_NAME string = resources.outputs.FOUNDRY_RESOURCE_NAME
output PUBLIC_BASE_URL string = resources.outputs.PUBLIC_BASE_URL
output TELEPHONY_PROVIDERS string = telephonyProviders
