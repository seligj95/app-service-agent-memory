targetScope = 'subscription'

@minLength(3)
@maxLength(32)
@description('The Azure Developer CLI environment name.')
param environmentName string

@description('The Azure region for all resources.')
param location string

var tags = {
  'azd-env-name': environmentName
  application: 'app-service-agent-memory'
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources './resources.bicep' = {
  name: 'agent-memory-resources'
  scope: resourceGroup
  params: {
    environmentName: environmentName
    location: location
    tags: tags
  }
}

output AZURE_LOCATION string = location
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output SERVICE_WEB_NAME string = resources.outputs.webAppName
output SERVICE_WEB_URI string = resources.outputs.webAppUri
output AZURE_OPENAI_NAME string = resources.outputs.openAIName
output COSMOS_ACCOUNT_NAME string = resources.outputs.cosmosAccountName
output REDIS_NAME string = resources.outputs.redisName
output KEY_VAULT_NAME string = resources.outputs.keyVaultName
