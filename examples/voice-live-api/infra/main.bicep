targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

// Voice Live gpt-realtime-mini regions verified 2026-09-25 — extend after checking https://learn.microsoft.com/en-us/azure/ai-services/speech-service/regions?tabs=voice-live
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

@allowed([
  'gpt-realtime-mini'
  'gpt-realtime-2.1-mini'
])
param voiceLiveModel string = 'gpt-realtime-mini'

param voiceLiveVoice string = 'en-US-Ava:DragonHDLatestNeural'

param maxConcurrentSessions int = 20

param webExists bool = false

@description('Shared mode: resource group of the platform/ azd project. Empty = standalone (own Foundry resource).')
param sharedResourceGroup string = ''
param sharedFoundryName string = ''
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
    voiceLiveModel: voiceLiveModel
    voiceLiveVoice: voiceLiveVoice
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
output VOICE_LIVE_ENDPOINT string = resources.outputs.VOICE_LIVE_ENDPOINT
output VOICE_LIVE_MODEL string = voiceLiveModel
output VOICE_LIVE_VOICE string = voiceLiveVoice
output VOICE_LIVE_API_VERSION string = '2026-07-15'
output FOUNDRY_RESOURCE_NAME string = resources.outputs.FOUNDRY_RESOURCE_NAME
output PUBLIC_BASE_URL string = resources.outputs.PUBLIC_BASE_URL
output TELEPHONY_PROVIDERS string = telephonyProviders
