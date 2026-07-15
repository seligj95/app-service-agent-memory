@minLength(3)
@maxLength(32)
param environmentName string

param location string
param tags object

var safeEnvironmentName = replace(toLower(environmentName), '_', '-')
var resourceToken = toLower(uniqueString(subscription().id, environmentName, location))
var webAppName = 'web-${take(safeEnvironmentName, 20)}-${resourceToken}'
var planName = 'plan-${take(safeEnvironmentName, 20)}-${resourceToken}'
var workspaceName = 'log-${take(safeEnvironmentName, 20)}-${resourceToken}'
var appInsightsName = 'appi-${take(safeEnvironmentName, 20)}-${resourceToken}'
var openAIName = 'aoai-${take(safeEnvironmentName, 18)}-${resourceToken}'
var cosmosAccountName = 'cosmos${take(replace(safeEnvironmentName, '-', ''), 16)}${resourceToken}'
var keyVaultName = 'kv${take(replace(safeEnvironmentName, '-', ''), 8)}${take(resourceToken, 12)}'
var redisName = 'redis-${take(safeEnvironmentName, 18)}-${resourceToken}'
var cosmosDatabaseName = 'agentmemory'
var cosmosContainerName = 'memories'
var chatDeploymentName = 'gpt-5-mini'
var embeddingDeploymentName = 'text-embedding-3-small'
var serviceName = 'web'

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    DisableIpMasking: false
    IngestionMode: 'LogAnalytics'
  }
}

resource appServicePlan 'Microsoft.Web/serverfarms@2024-11-01' = {
  name: planName
  location: location
  kind: 'linux'
  tags: tags
  sku: {
    name: 'P0v4'
    tier: 'PremiumV4'
    capacity: 1
  }
  properties: {
    reserved: true
    zoneRedundant: false
  }
}

resource webApp 'Microsoft.Web/sites@2024-11-01' = {
  name: webAppName
  location: location
  kind: 'app,linux'
  tags: union(tags, {
    'azd-service-name': serviceName
  })
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    clientAffinityEnabled: false
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.13'
      alwaysOn: true
      appCommandLine: 'python -m uvicorn app.main:app --host 0.0.0.0 --port 8000'
      healthCheckPath: '/health'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
    }
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource openAI 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: openAIName
  location: location
  kind: 'OpenAI'
  tags: tags
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: openAIName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
}

resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openAI
  name: chatDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5-mini'
      version: '2025-08-07'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: openAI
  name: embeddingDeploymentName
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'text-embedding-3-small'
      version: '1'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [
    chatDeployment
  ]
}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' = {
  name: cosmosAccountName
  location: location
  kind: 'GlobalDocumentDB'
  tags: tags
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: [
      {
        name: 'EnableServerless'
      }
      {
        name: 'EnableNoSQLVectorSearch'
      }
    ]
    disableLocalAuth: true
    minimalTlsVersion: 'Tls12'
    publicNetworkAccess: 'Enabled'
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2025-04-15' = {
  parent: cosmosAccount
  name: cosmosDatabaseName
  properties: {
    resource: {
      id: cosmosDatabaseName
    }
  }
}

resource cosmosContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2025-04-15' = {
  parent: cosmosDatabase
  name: cosmosContainerName
  properties: {
    resource: {
      id: cosmosContainerName
      partitionKey: {
        paths: [
          '/user_id'
        ]
        kind: 'Hash'
        version: 2
      }
      indexingPolicy: {
        automatic: true
        indexingMode: 'consistent'
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
          {
            path: '/embedding/*'
          }
        ]
        vectorIndexes: [
          {
            path: '/embedding'
            type: 'quantizedFlat'
          }
        ]
      }
      vectorEmbeddingPolicy: {
        vectorEmbeddings: [
          {
            path: '/embedding'
            dataType: 'float32'
            distanceFunction: 'cosine'
            dimensions: 1536
          }
        ]
      }
    }
  }
}

module redis 'br/public:avm/res/cache/redis-enterprise:0.5.1' = {
  name: 'managed-redis'
  params: {
    name: redisName
    location: location
    skuName: 'Balanced_B0'
    highAvailability: 'Disabled'
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    enableTelemetry: false
    tags: tags
    database: {
      accessKeysAuthentication: 'Disabled'
      clientProtocol: 'Encrypted'
      clusteringPolicy: 'OSSCluster'
      evictionPolicy: 'VolatileLRU'
      accessPolicyAssignments: [
        {
          name: 'webapp'
          accessPolicyName: 'default'
          userObjectId: webApp.identity.principalId
        }
      ]
    }
  }
}

resource webAppSettings 'Microsoft.Web/sites/config@2024-11-01' = {
  parent: webApp
  name: 'appsettings'
  properties: {
    APP_MODE: 'azure'
    CREDENTIAL_MODE: 'managed-identity'
    AZURE_OPENAI_ENDPOINT: openAI.properties.endpoint
    AZURE_OPENAI_CHAT_DEPLOYMENT: chatDeploymentName
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: embeddingDeploymentName
    AZURE_OPENAI_API_VERSION: 'preview'
    AZURE_OPENAI_EMBEDDING_API_VERSION: '2024-10-21'
    COSMOS_ENDPOINT: cosmosAccount.properties.documentEndpoint
    COSMOS_DATABASE: cosmosDatabaseName
    COSMOS_CONTAINER: cosmosContainerName
    REDIS_HOST: redis.outputs.hostName
    REDIS_PORT: string(redis.outputs.port)
    HISTORY_TTL_SECONDS: '604800'
    HISTORY_MAX_MESSAGES: '40'
    API_REQUESTS_PER_MINUTE: '120'
    APPLICATIONINSIGHTS_CONNECTION_STRING: appInsights.properties.ConnectionString
    OTEL_SERVICE_NAME: 'app-service-agent-memory'
    SCM_DO_BUILD_DURING_DEPLOYMENT: 'true'
    ENABLE_ORYX_BUILD: 'true'
    WEBSITE_HEALTHCHECK_MAXPINGFAILURES: '3'
    WEBSITE_HTTPLOGGING_RETENTION_DAYS: '7'
  }
}

resource openAIRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openAI.id, webApp.id, 'Cognitive Services OpenAI User')
  scope: openAI
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, webApp.id, 'Key Vault Secrets User')
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4633458b-17de-408a-b874-0445c86b69e6'
    )
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, webApp.id, 'Cosmos DB Built-in Data Contributor')
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: webApp.identity.principalId
    scope: cosmosAccount.id
  }
}

output webAppName string = webApp.name
output webAppUri string = 'https://${webApp.properties.defaultHostName}'
output openAIName string = openAI.name
output cosmosAccountName string = cosmosAccount.name
output redisName string = redis.outputs.name
output keyVaultName string = keyVault.name
