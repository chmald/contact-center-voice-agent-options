param containerAppName string

resource existingWeb 'Microsoft.App/containerApps@2025-07-01' existing = {
  name: containerAppName
}

output image string = existingWeb.properties.template.containers[0].image
