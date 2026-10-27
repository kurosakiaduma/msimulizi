// Msimulizi — Azure infrastructure
// Deploy with: azd up
// All secrets are stored in Key Vault; no secrets are committed to the repository.

targetScope = 'resourceGroup'

// ---------------------------------------------------------------------------
// Parameters
// ---------------------------------------------------------------------------

@description('Environment name used as a prefix for all resources (e.g. dev, prod).')
param environmentName string

@description('Primary Azure region for all resources.')
param location string = resourceGroup().location

@description('Optional: override the Cosmos DB account name.')
param cosmosAccountName string = ''

@allowed([
  'bootstrap'
  'preserve'
])
@description('bootstrap writes placeholder Key Vault credentials; preserve leaves rotated values untouched.')
param keyMode string = 'bootstrap'

// ---------------------------------------------------------------------------
// Variables
// ---------------------------------------------------------------------------

var prefix = 'msim-${environmentName}'
var cosmosName = empty(cosmosAccountName) ? '${prefix}-cosmos' : cosmosAccountName
var kvName = '${prefix}-kv'
var storageAccountName = replace('${prefix}stor', '-', '')  // storage names: alphanumeric only
var speechName = '${prefix}-speech'
var contentSafetyName = '${prefix}-cs'
var appInsightsName = '${prefix}-ai'
var lawName = '${prefix}-law'
var acaEnvName = '${prefix}-acaenv'
var backendAppName = '${prefix}-backend'
var frontendAppName = '${prefix}-frontend'
var managedIdentityName = '${prefix}-mid'
var acrName = toLower(replace('${prefix}acr${uniqueString(resourceGroup().id)}', '-', ''))
var registryServer = acr.properties.loginServer
// Bootstrap image used only while provisioning. `azd deploy` replaces it with
// the image it builds and pushes to the environment ACR.
var bootstrapImage = 'mcr.microsoft.com/azuredocs/containerapps-helloworld:latest'

// Cosmos DB containers
var cosmosContainers = [
  {
    name: 'match_state_snapshots'
    partitionKey: '/match_id'
    ttl: -1  // no TTL
  }
  {
    name: 'key_moments'
    partitionKey: '/match_id'
    ttl: -1
  }
  {
    name: 'narration_cache'
    partitionKey: '/profile_key'
    ttl: -1
  }
  {
    name: 'overlay_cards'
    partitionKey: '/match_id'
    ttl: 86400  // 24 hours default TTL (spotlight cards use per-item override via _ts + TTL)
  }
  {
    name: 'audit_log'
    partitionKey: '/match_id'
    ttl: -1  // never expire audit entries
  }
  {
    name: 'corrections'
    partitionKey: '/match_id'
    ttl: -1
  }
]

// ---------------------------------------------------------------------------
// User-assigned managed identity
// Used by Container Apps to pull images and access Azure services.
// ---------------------------------------------------------------------------

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
}

// ---------------------------------------------------------------------------
// Azure Container Registry — images for both Container Apps
// ---------------------------------------------------------------------------

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, managedIdentity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Log Analytics Workspace (required by Container Apps environment)
// ---------------------------------------------------------------------------

resource law 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: lawName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

// ---------------------------------------------------------------------------
// Application Insights
// ---------------------------------------------------------------------------

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: law.id
  }
}

// ---------------------------------------------------------------------------
// Key Vault
// ---------------------------------------------------------------------------

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: kvName
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
    enabledForDeployment: false
    enabledForTemplateDeployment: false
    enabledForDiskEncryption: false
  }
}

// Placeholder secrets — created only in bootstrap mode. Rotate with:
//   az keyvault secret set --vault-name <kvName> --name <secret-name> --value <value>
// then set KEY_MODE=preserve so later deployments do not reset them.

resource kvSecretMcpApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (keyMode == 'bootstrap') {
  parent: keyVault
  name: 'mcp-api-key'
  properties: {
    value: 'PLACEHOLDER-set-before-first-use'
    contentType: 'text/plain'
  }
}

resource kvSecretReviewerApiKey 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (keyMode == 'bootstrap') {
  parent: keyVault
  name: 'reviewer-api-key'
  properties: {
    value: 'PLACEHOLDER-set-before-first-use'
    contentType: 'text/plain'
  }
}

// Grant the managed identity permission to read secrets
var kvSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6' // Key Vault Secrets User

resource kvRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, managedIdentity.id, kvSecretsUserRoleId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', kvSecretsUserRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Cosmos DB account and containers
// ---------------------------------------------------------------------------

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2024-02-15-preview' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
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
    enableFreeTier: false
    capabilities: []
  }
}

resource cosmosDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-02-15-preview' = {
  parent: cosmosAccount
  name: 'msimulizi'
  properties: {
    resource: {
      id: 'msimulizi'
    }
    options: {
      throughput: 400
    }
  }
}

// Deploy each container with its partition key and TTL policy
resource cosmosContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-02-15-preview' = [for c in cosmosContainers: {
  parent: cosmosDatabase
  name: c.name
  properties: {
    resource: {
      id: c.name
      partitionKey: {
        paths: [c.partitionKey]
        kind: 'Hash'
      }
      defaultTtl: c.ttl  // -1 = off; positive integer = container-level default in seconds
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [{ path: '/*' }]
        excludedPaths: [{ path: '/"_etag"/?' }]
      }
    }
  }
}]

// ---------------------------------------------------------------------------
// Cosmos DB RBAC — custom create-only role for the audit_log container
//
// The built-in "Cosmos DB Built-in Data Contributor" role allows reads and
// writes. For audit_log we want CREATE (insert) only — no replace/delete/read
// from the app identity. We grant the standard Data Contributor to the managed
// identity for all containers, then restrict audit_log via a custom role.
// ---------------------------------------------------------------------------

// Built-in Cosmos DB Data Contributor role (read + write, all containers)
var cosmosDataContributorRoleId = '00000000-0000-0000-0000-000000000002'

resource cosmosRoleAssignment 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-02-15-preview' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, managedIdentity.id, cosmosDataContributorRoleId)
  properties: {
    roleDefinitionId: '${cosmosAccount.id}/sqlRoleDefinitions/${cosmosDataContributorRoleId}'
    principalId: managedIdentity.properties.principalId
    scope: cosmosAccount.id
  }
}

// Custom create-only role scoped to audit_log
resource auditLogCreateOnlyRoleDef 'Microsoft.DocumentDB/databaseAccounts/sqlRoleDefinitions@2024-02-15-preview' = {
  parent: cosmosAccount
  name: guid(cosmosAccount.id, 'audit-log-create-only')
  properties: {
    roleName: 'Msimulizi Audit Log Create Only'
    type: 'CustomRole'
    assignableScopes: [
      '${cosmosAccount.id}/dbs/msimulizi/colls/audit_log'
    ]
    permissions: [
      {
        dataActions: [
          'Microsoft.DocumentDB/databaseAccounts/readMetadata'
          'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers/items/create'
        ]
        notDataActions: []
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Azure Blob Storage — audio container with public read (anonymous blob read)
// ---------------------------------------------------------------------------

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: true  // required for public-read audio URLs
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource audioContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'audio'
  properties: {
    publicAccess: 'Blob'  // anonymous read access to blobs (not container listing)
  }
}

// Grant the managed identity Storage Blob Data Contributor on the storage account
var storageBlobDataContributorRoleId = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storageAccount.id, managedIdentity.id, storageBlobDataContributorRoleId)
  scope: storageAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', storageBlobDataContributorRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Azure AI Speech
// ---------------------------------------------------------------------------

resource speechService 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: speechName
  location: location
  kind: 'SpeechServices'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: speechName
  }
}

// Grant managed identity Speech User (synthesis + voice catalogue)
var cognitiveServicesUserRoleId = 'a97b65f3-24c7-4388-baec-2e87135dc908' // Cognitive Services User
var cognitiveServicesOpenAIUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd' // Cognitive Services OpenAI User
var cognitiveServicesSpeechUserRoleId = 'f2dc8367-1007-4938-bd23-fe263f013447' // Cognitive Services Speech User

resource speechRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(speechService.id, managedIdentity.id, cognitiveServicesSpeechUserRoleId)
  scope: speechService
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesSpeechUserRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Azure AI Content Safety
// ---------------------------------------------------------------------------

resource contentSafety 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: contentSafetyName
  location: location
  kind: 'ContentSafety'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: contentSafetyName
  }
}

resource contentSafetyRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(contentSafety.id, managedIdentity.id, cognitiveServicesUserRoleId)
  scope: contentSafety
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesUserRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ---------------------------------------------------------------------------
// Microsoft Foundry (Azure OpenAI) account + model deployments
// Named deployments match config/foundry_models.yaml
// ---------------------------------------------------------------------------

resource foundryAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: '${prefix}-foundry'
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    publicNetworkAccess: 'Enabled'
    customSubDomainName: '${prefix}-foundry'
  }
}

resource foundryRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundryAccount.id, managedIdentity.id, cognitiveServicesOpenAIUserRoleId)
  scope: foundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAIUserRoleId)
    principalId: managedIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Model deployments — names match config/foundry_models.yaml
// GA models retiring after the 10 Nov 2026 judging window:
//   gpt-5.4 (2026-03-05) → 2027-09-02
//   gpt-5.4-mini (2026-03-17) → 2027-09-21
// Verify at: https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule

resource deploymentExplainer 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: foundryAccount
  name: 'msimulizi-explainer'
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4-mini'
      version: '2026-03-17'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource deploymentNarratorSw 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: foundryAccount
  name: 'msimulizi-narrator-sw'
  dependsOn: [deploymentExplainer]
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4'
      version: '2026-03-05'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource deploymentNarratorEnFr 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: foundryAccount
  name: 'msimulizi-narrator-en-fr'
  dependsOn: [deploymentNarratorSw]
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4-mini'
      version: '2026-03-17'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource deploymentVerifier 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: foundryAccount
  name: 'msimulizi-verifier'
  dependsOn: [deploymentNarratorEnFr]
  sku: {
    name: 'GlobalStandard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-5.4-mini'
      version: '2026-03-17'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// ---------------------------------------------------------------------------
// Container Apps environment
// ---------------------------------------------------------------------------

resource acaEnv 'Microsoft.App/managedEnvironments@2023-11-02-preview' = {
  name: acaEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Backend Container App
// min 1 replica, scale-to-zero disabled
// ---------------------------------------------------------------------------

resource backendApp 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: backendAppName
  location: location
  tags: {
    'azd-service-name': 'backend'
  }
  dependsOn: [
    acrPullRoleAssignment
    kvRoleAssignment
    cosmosRoleAssignment
    storageRoleAssignment
    speechRoleAssignment
    contentSafetyRoleAssignment
    foundryRoleAssignment
  ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        corsPolicy: {
          allowedOrigins: ['*']  // tightened to deployed UI origin in task 31
          allowedMethods: ['GET', 'POST', 'PATCH', 'OPTIONS']
          allowedHeaders: ['*']
          allowCredentials: false
        }
      }
      registries: [
        {
          server: registryServer
          identity: managedIdentity.id
        }
      ]
      secrets: [
        {
          name: 'appinsights-conn'
          value: appInsights.properties.ConnectionString
        }
        {
          name: 'mcp-api-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/mcp-api-key'
          identity: managedIdentity.id
        }
        {
          name: 'reviewer-api-key'
          keyVaultUrl: '${keyVault.properties.vaultUri}secrets/reviewer-api-key'
          identity: managedIdentity.id
        }
      ]
    }
    template: {
      scale: {
        minReplicas: 1  // scale-to-zero disabled; in-memory state must survive
        maxReplicas: 1  // no shared backplane yet; WebSocket/session state stays on one replica
      }
      containers: [
        {
          name: 'backend'
          image: bootstrapImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: [
            {
              name: 'AZURE_CLIENT_ID'
              value: managedIdentity.properties.clientId
            }
            {
              name: 'KEY_VAULT_URL'
              value: keyVault.properties.vaultUri
            }
            {
              name: 'COSMOS_ENDPOINT'
              value: cosmosAccount.properties.documentEndpoint
            }
            {
              name: 'COSMOS_DATABASE'
              value: 'msimulizi'
            }
            {
              name: 'FOUNDRY_ENDPOINT'
              value: foundryAccount.properties.endpoint
            }
            {
              name: 'SPEECH_ENDPOINT'
              value: 'https://${speechName}.cognitiveservices.azure.com/'
            }
            {
              name: 'CONTENT_SAFETY_ENDPOINT'
              value: contentSafety.properties.endpoint
            }
            {
              name: 'STORAGE_ACCOUNT_URL'
              value: storageAccount.properties.primaryEndpoints.blob
            }
            {
              name: 'AUDIO_BLOB_ACCOUNT_URL'
              value: storageAccount.properties.primaryEndpoints.blob
            }
            {
              name: 'AUDIO_BLOB_CONTAINER'
              value: 'audio'
            }
            {
              name: 'SPEECH_USE_MANAGED_IDENTITY'
              value: 'true'
            }
            {
              name: 'APP_ENV'
              value: 'production'
            }
            {
              name: 'FOUNDRY_REASONING_EFFORT'
              value: 'none'
            }
            {
              name: 'MSIMULIZI_ALLOWED_ORIGINS'
              value: 'https://${prefix}-frontend.${acaEnv.properties.defaultDomain}'
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              secretRef: 'appinsights-conn'
            }
            {
              name: 'MCP_API_KEY'
              secretRef: 'mcp-api-key'
            }
            {
              name: 'MSIMULIZI_REVIEWER_KEY'
              secretRef: 'reviewer-api-key'
            }
            {
              name: 'ENVIRONMENT_NAME'
              value: environmentName
            }
          ]
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Frontend Container App
// ---------------------------------------------------------------------------

resource frontendApp 'Microsoft.App/containerApps@2023-11-02-preview' = {
  name: frontendAppName
  location: location
  tags: {
    'azd-service-name': 'frontend'
  }
  dependsOn: [
    acrPullRoleAssignment
  ]
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${managedIdentity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: acaEnv.id
    configuration: {
      ingress: {
        external: true
        targetPort: 3000
        transport: 'http'
      }
      registries: [
        {
          server: registryServer
          identity: managedIdentity.id
        }
      ]
    }
    template: {
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
      containers: [
        {
          name: 'frontend'
          image: bootstrapImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
          env: [
            {
              name: 'BACKEND_URL'
              value: 'https://${backendApp.properties.configuration.ingress.fqdn}'
            }
            {
              name: 'WS_URL'
              value: 'wss://${backendApp.properties.configuration.ingress.fqdn}/ws'
            }
          ]
        }
      ]
    }
  }
}

// ---------------------------------------------------------------------------
// Outputs (consumed by azd and CI)
// ---------------------------------------------------------------------------

output backendUrl string = 'https://${backendApp.properties.configuration.ingress.fqdn}'
output frontendUrl string = 'https://${frontendApp.properties.configuration.ingress.fqdn}'
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output keyVaultUri string = keyVault.properties.vaultUri
output storageAccountUrl string = storageAccount.properties.primaryEndpoints.blob
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output foundryEndpoint string = foundryAccount.properties.endpoint
output speechEndpoint string = 'https://${speechName}.cognitiveservices.azure.com/'
output contentSafetyEndpoint string = contentSafety.properties.endpoint
output managedIdentityClientId string = managedIdentity.properties.clientId
output AZURE_CONTAINER_REGISTRY_ENDPOINT string = acr.properties.loginServer
output containerRegistryName string = acr.name
