param environmentName string
param location string
@description('Region for Container Apps, ACR, Log Analytics, and the managed identity. Defaults to location; set it when Container Apps capacity is constrained in the AI region.')
param appLocation string = location
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
param realtimeDeploymentName string
param realtimeDeploymentCapacity int

@allowed([
  'OnceNewDefaultVersionAvailable'
  'OnceCurrentVersionExpired'
  'NoAutoUpgrade'
])
param versionUpgradeOption string

param realtimeVoice string
param maxConcurrentSessions int
param webExists bool
param tags object

@description('Shared platform resource group (platform/ azd project). Empty = standalone mode.')
param sharedResourceGroup string = ''
@description('Existing Foundry (AI Services) resource in sharedResourceGroup that already hosts the realtime deployment.')
param sharedFoundryName string = ''
param searchServiceName string = ''
param searchIndexName string = 'knowledge'
param searchSemanticConfig string = 'default'
param acsResourceName string = ''
@description('Comma list of phone channels to enable: acs, twilio. Empty = browser only.')
param telephonyProviders string = ''
@secure()
param telephonyWebhookSecret string = ''
@secure()
param acsEventGridSecret string = ''
@secure()
param twilioAuthToken string = ''
param telephonyOverflowNumber string = ''

var suffix = uniqueString(subscription().id, environmentName, location)
var logName = 'log-${suffix}'
var environmentNameShort = 'cae-${suffix}'
var acrName = 'cr${suffix}'
var identityName = 'id-${suffix}'
var foundryName = 'ais-${suffix}'
var webName = 'ca-web-${suffix}'
var defaultImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'
var deploymentName = empty(realtimeDeploymentName) ? realtimeModel : realtimeDeploymentName
var modelVersions = {
  'gpt-realtime-2.1-mini': '2026-07-07'
  'gpt-realtime-mini': '2025-12-15'
}
var resolvedModelVersion = empty(realtimeModelVersion) ? modelVersions[realtimeModel] : realtimeModelVersion
var openAIUserRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
var acrPullRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
var hasSharedRg = !empty(sharedResourceGroup)
var useSharedFoundry = hasSharedRg && !empty(sharedFoundryName)
var useSearch = hasSharedRg && !empty(searchServiceName)
var useAcs = hasSharedRg && !empty(acsResourceName)

resource logs 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: logName
  location: appLocation
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource managedEnvironment 'Microsoft.App/managedEnvironments@2025-07-01' = {
  name: environmentNameShort
  location: appLocation
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2025-11-01' = {
  name: acrName
  location: appLocation
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

resource uami 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: appLocation
  tags: tags
}

resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, uami.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: acrPullRoleId
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = if (!useSharedFoundry) {
  name: foundryName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: foundryName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

// Standalone mode only. In shared mode the platform/ project owns the single realtime
// deployment so both apps draw from one quota pool.
resource realtimeDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (!useSharedFoundry) {
  parent: foundry
  name: deploymentName
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
    versionUpgradeOption: versionUpgradeOption
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}

resource uamiOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!useSharedFoundry) {
  name: guid(resourceGroup().id, foundryName, uami.id, openAIUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: openAIUserRoleId
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

resource principalOpenAIUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!useSharedFoundry && !empty(principalId)) {
  name: guid(resourceGroup().id, foundryName, principalId, openAIUserRoleId)
  scope: foundry
  properties: {
    roleDefinitionId: openAIUserRoleId
    principalId: principalId
    principalType: principalType
  }
}

// Shared mode: grant this app's identity access to the platform's single AI endpoint,
// knowledge index, and ACS resource (the deploying user's roles come from the platform).
module sharedAccess 'shared-access.bicep' = if (hasSharedRg) {
  name: 'shared-access-${suffix}'
  scope: resourceGroup(hasSharedRg ? sharedResourceGroup : resourceGroup().name)
  params: {
    foundryName: useSharedFoundry ? sharedFoundryName : ''
    foundryRoleIds: [
      openAIUserRoleId
    ]
    searchServiceName: useSearch ? searchServiceName : ''
    acsResourceName: useAcs ? acsResourceName : ''
    principalId: uami.properties.principalId
  }
}

var foundrySubDomain = useSharedFoundry ? sharedAccess!.outputs.foundryCustomSubDomain : foundry!.properties.customSubDomainName
var openAIEndpoint = 'https://${foundrySubDomain}.openai.azure.com'
var publicBaseUrl = 'https://${webName}.${managedEnvironment.properties.defaultDomain}'

var baseEnv = [
  {
    name: 'AZURE_OPENAI_ENDPOINT'
    value: openAIEndpoint
  }
  {
    name: 'AZURE_OPENAI_REALTIME_DEPLOYMENT'
    value: deploymentName
  }
  {
    name: 'AZURE_OPENAI_REALTIME_MODEL'
    value: realtimeModel
  }
  {
    name: 'REALTIME_VOICE'
    value: realtimeVoice
  }
  {
    name: 'AZURE_CLIENT_ID'
    value: uami.properties.clientId
  }
  {
    name: 'MAX_CONCURRENT_SESSIONS'
    value: string(maxConcurrentSessions)
  }
  {
    name: 'LOG_LEVEL'
    value: 'INFO'
  }
]
var searchEnv = useSearch ? [
  {
    name: 'AZURE_SEARCH_ENDPOINT'
    value: sharedAccess!.outputs.searchEndpoint
  }
  {
    name: 'AZURE_SEARCH_INDEX'
    value: searchIndexName
  }
  {
    name: 'AZURE_SEARCH_SEMANTIC_CONFIG'
    value: searchSemanticConfig
  }
] : []
var telephonyEnv = empty(telephonyProviders) ? [] : concat([
  {
    name: 'TELEPHONY_PROVIDERS'
    value: telephonyProviders
  }
  {
    name: 'PUBLIC_BASE_URL'
    value: publicBaseUrl
  }
  {
    name: 'TELEPHONY_OVERFLOW_NUMBER'
    value: telephonyOverflowNumber
  }
], empty(telephonyWebhookSecret) ? [] : [
  {
    name: 'TELEPHONY_WEBHOOK_SECRET'
    secretRef: 'telephony-webhook-secret'
  }
], useAcs ? [
  {
    name: 'ACS_ENDPOINT'
    value: sharedAccess!.outputs.acsEndpoint
  }
] : [], useAcs && !empty(acsEventGridSecret) ? [
  {
    name: 'ACS_EVENTGRID_SECRET'
    secretRef: 'acs-eventgrid-secret'
  }
] : [], empty(twilioAuthToken) ? [] : [
  {
    name: 'TWILIO_AUTH_TOKEN'
    secretRef: 'twilio-auth-token'
  }
])
var appSecrets = concat(useAcs && !empty(acsEventGridSecret) ? [
  {
    name: 'acs-eventgrid-secret'
    value: acsEventGridSecret
  }
] : [], empty(telephonyWebhookSecret) ? [] : [
  {
    name: 'telephony-webhook-secret'
    value: telephonyWebhookSecret
  }
], empty(twilioAuthToken) ? [] : [
  {
    name: 'twilio-auth-token'
    value: twilioAuthToken
  }
])

module existingImage 'fetch-container-image.bicep' = if (webExists) {
  name: 'fetch-image-${suffix}'
  params: {
    containerAppName: webName
  }
}

// Admission control (MAX_CONCURRENT_SESSIONS) is per replica, so one replica makes it a global cap.
// To scale out, raise maxReplicas and account for maxConcurrentSessions * replica count.
resource web 'Microsoft.App/containerApps@2025-07-01' = {
  name: webName
  location: appLocation
  tags: union(tags, {
    'azd-service-name': 'web'
  })
  // Wait for AcrPull and the realtime model deployment before creating the first app revision.
  dependsOn: [
    acrPull
    realtimeDeployment
  ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${uami.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: managedEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: uami.id
        }
      ]
      secrets: appSecrets
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webExists ? existingImage!.outputs.image : defaultImage
          env: concat(baseEnv, searchEnv, telephonyEnv)
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 30
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/healthz'
                port: 8000
                scheme: 'HTTP'
              }
              initialDelaySeconds: 5
              periodSeconds: 10
            }
          ]
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.properties.loginServer
output AZURE_CONTAINER_REGISTRY_NAME string = acr.name
output SERVICE_WEB_NAME string = web.name
output SERVICE_WEB_URI string = 'https://${web.properties.configuration.ingress.fqdn}'
output AZURE_OPENAI_ENDPOINT string = openAIEndpoint
output AZURE_OPENAI_REALTIME_DEPLOYMENT string = deploymentName
output AZURE_OPENAI_REALTIME_MODEL_VERSION string = resolvedModelVersion
output FOUNDRY_RESOURCE_NAME string = useSharedFoundry ? sharedFoundryName : foundryName
output PUBLIC_BASE_URL string = publicBaseUrl
