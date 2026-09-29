targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

// Global Standard realtime regions verified 2026-09-25 - re-check https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability
@allowed([
  'canadacentral'
  'centralus'
  'eastus2'
  'francecentral'
  'swedencentral'
  'southindia'
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
  'gpt-realtime-2.1-mini'
  'gpt-realtime-mini'
])
param realtimeModel string = 'gpt-realtime-2.1-mini'

param realtimeModelVersion string = ''

param realtimeDeploymentName string = ''

@description('Realtime Global Standard capacity units. gpt-realtime-2.1-mini: 1 unit = 10,000 TPM + 20 RPM (10 = 100K TPM, what the portal shows). The usage-list quota row is labelled "Requests Per Minute - <model> - GlobalStandard" but counts units. Many subscriptions start with 10. The preprovision hook (scripts/check-realtime-quota.ps1) stops early if this exceeds what is available.')
param realtimeDeploymentCapacity int = 10

@allowed([
  'OnceNewDefaultVersionAvailable'
  'OnceCurrentVersionExpired'
  'NoAutoUpgrade'
])
param versionUpgradeOption string = 'OnceCurrentVersionExpired'

param realtimeVoice string = 'marin'

param maxConcurrentSessions int = 20

param webExists bool = false

@description('Shared mode: resource group of the platform/ azd project. Empty = standalone (own Foundry resource + deployment).')
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
    realtimeModel: realtimeModel
    realtimeModelVersion: realtimeModelVersion
    realtimeDeploymentName: realtimeDeploymentName
    realtimeDeploymentCapacity: realtimeDeploymentCapacity
    versionUpgradeOption: versionUpgradeOption
    realtimeVoice: realtimeVoice
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
output AZURE_OPENAI_ENDPOINT string = resources.outputs.AZURE_OPENAI_ENDPOINT
output AZURE_OPENAI_REALTIME_DEPLOYMENT string = resources.outputs.AZURE_OPENAI_REALTIME_DEPLOYMENT
output AZURE_OPENAI_REALTIME_MODEL string = realtimeModel
output AZURE_OPENAI_REALTIME_MODEL_VERSION string = resources.outputs.AZURE_OPENAI_REALTIME_MODEL_VERSION
output REALTIME_VOICE string = realtimeVoice
output FOUNDRY_RESOURCE_NAME string = resources.outputs.FOUNDRY_RESOURCE_NAME
output PUBLIC_BASE_URL string = resources.outputs.PUBLIC_BASE_URL
output TELEPHONY_PROVIDERS string = telephonyProviders
