// Shared test platform: ONE Foundry (AI Services) endpoint + ONE realtime deployment + one Foundry project (voice agent),
// plus the knowledge index (Azure AI Search) and the phone channel (Azure Communication
// Services). Both example apps attach to these in "shared mode" so a single subscription
// and a single AI endpoint carry the whole comparison within one quota pool.
targetScope = 'subscription'

@minLength(1)
@maxLength(64)
param environmentName string

// Regions where Voice Live (gpt-realtime-mini) AND Global Standard realtime deployments are
// both available (verified 2026-09-25). Re-check before adding more.
@allowed([
  'centralus'
  'eastus2'
  'swedencentral'
])
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
  'gpt-realtime-2.1-mini'
  'gpt-realtime-mini'
])
param realtimeModel string = 'gpt-realtime-2.1-mini'

param realtimeModelVersion string = ''

@description('Realtime Global Standard capacity units. gpt-realtime-2.1-mini: 1 unit = 10,000 TPM + 20 RPM (10 = 100K TPM, what the portal shows). The usage-list quota row is labelled "Requests Per Minute - <model> - GlobalStandard" but counts units. Many subscriptions start with 10. The preprovision hook (scripts/check-realtime-quota.ps1) stops early if this exceeds what is available.')
param realtimeDeploymentCapacity int = 10

param deploySearch bool = true

param deployCommunicationServices bool = true

@allowed([
  'United States'
  'Europe'
  'UK'
  'Canada'
  'Australia'
])
param communicationDataLocation string = 'United States'

var tags = {
  'azd-env-name': environmentName
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module platform 'modules/platform.bicep' = {
  name: 'platform-${uniqueString(subscription().id, environmentName, location)}'
  scope: rg
  params: {
    environmentName: environmentName
    location: location
    principalId: principalId
    principalType: principalType
    realtimeModel: realtimeModel
    realtimeModelVersion: realtimeModelVersion
    realtimeDeploymentCapacity: realtimeDeploymentCapacity
    deploySearch: deploySearch
    deployCommunicationServices: deployCommunicationServices
    communicationDataLocation: communicationDataLocation
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_TENANT_ID string = tenant().tenantId
output SHARED_RESOURCE_GROUP string = rg.name
output SHARED_FOUNDRY_NAME string = platform.outputs.FOUNDRY_NAME
output SHARED_FOUNDRY_PROJECT string = platform.outputs.FOUNDRY_PROJECT_NAME
output SHARED_FOUNDRY_PROJECT_ENDPOINT string = platform.outputs.FOUNDRY_PROJECT_ENDPOINT
output SHARED_VOICE_LIVE_ENDPOINT string = platform.outputs.VOICE_LIVE_ENDPOINT
output SHARED_OPENAI_ENDPOINT string = platform.outputs.OPENAI_ENDPOINT
output AZURE_OPENAI_REALTIME_DEPLOYMENT string = platform.outputs.REALTIME_DEPLOYMENT
output AZURE_OPENAI_REALTIME_MODEL string = realtimeModel
output AZURE_OPENAI_REALTIME_MODEL_VERSION string = platform.outputs.REALTIME_MODEL_VERSION
output AZURE_SEARCH_SERVICE_NAME string = platform.outputs.SEARCH_SERVICE_NAME
output AZURE_SEARCH_ENDPOINT string = platform.outputs.SEARCH_ENDPOINT
output ACS_RESOURCE_NAME string = platform.outputs.ACS_NAME
output ACS_ENDPOINT string = platform.outputs.ACS_ENDPOINT
