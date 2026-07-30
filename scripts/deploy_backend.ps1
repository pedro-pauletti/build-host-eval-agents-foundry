[CmdletBinding()]
param(
    [string]$EnvPath = (Join-Path (Split-Path $PSScriptRoot -Parent) ".env")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

function Read-DotEnv {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing .env file at $Path"
    }

    $values = @{}
    foreach ($line in Get-Content -Path $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }

        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) {
            $values[$parts[0].Trim()] = $parts[1].Trim()
        }
    }
    return $values
}

function Update-DotEnvValue {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    $line = "$Name=$Value"
    if (-not (Test-Path $Path)) {
        Set-Content -Path $Path -Value $line
        return
    }

    $lines = @(Get-Content -Path $Path)
    $updated = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*$([regex]::Escape($Name))=") {
            $lines[$i] = $line
            $updated = $true
        }
    }

    if (-not $updated) {
        $lines += $line
    }
    Set-Content -Path $Path -Value $lines
}

function Invoke-Az {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    & az @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "az $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

function Get-Required {
    param(
        [hashtable]$Values,
        [string]$Name
    )
    if (-not $Values.ContainsKey($Name) -or [string]::IsNullOrWhiteSpace($Values[$Name])) {
        throw "Missing required .env value: $Name"
    }
    return $Values[$Name]
}

function Test-ContainerAppExists {
    param(
        [string]$ResourceGroup,
        [string]$Name
    )
    $null = & az containerapp show -g $ResourceGroup -n $Name --query name -o tsv 2>$null
    return $LASTEXITCODE -eq 0
}

$envValues = Read-DotEnv -Path $EnvPath
$resourceGroup = Get-Required $envValues "AZURE_RESOURCE_GROUP"
$acrName = Get-Required $envValues "AZURE_CONTAINER_REGISTRY_NAME"
$containerAppsEnvironment = Get-Required $envValues "AZURE_CONTAINER_APPS_ENVIRONMENT_NAME"
$identityId = Get-Required $envValues "AZURE_APP_IDENTITY_ID"
$registryServer = if ($envValues.ContainsKey("AZURE_CONTAINER_REGISTRY_ENDPOINT") -and $envValues["AZURE_CONTAINER_REGISTRY_ENDPOINT"]) {
    $envValues["AZURE_CONTAINER_REGISTRY_ENDPOINT"]
} else {
    "$acrName.azurecr.io"
}

if ($envValues.ContainsKey("AZURE_SUBSCRIPTION_ID") -and $envValues["AZURE_SUBSCRIPTION_ID"]) {
    Invoke-Az account set --subscription $envValues["AZURE_SUBSCRIPTION_ID"]
}

Write-Host "Building zava-api:v1 in ACR..."
Invoke-Az acr build -r $acrName -t "zava-api:v1" "services\zava-api" --no-logs

Write-Host "Building zava-mcp:v1 in ACR..."
Invoke-Az acr build -r $acrName -t "zava-mcp:v1" "services\zava-mcp" --no-logs

$apiImage = "$registryServer/zava-api:v1"
$mcpImage = "$registryServer/zava-mcp:v1"

if (Test-ContainerAppExists -ResourceGroup $resourceGroup -Name "zava-api") {
    Write-Host "Updating zava-api..."
    Invoke-Az containerapp identity assign -g $resourceGroup -n "zava-api" --user-assigned $identityId
    Invoke-Az containerapp registry set -g $resourceGroup -n "zava-api" --server $registryServer --identity $identityId
    Invoke-Az containerapp update -g $resourceGroup -n "zava-api" --image $apiImage --min-replicas 1 --max-replicas 2 --cpu 0.5 --memory "1.0Gi"
} else {
    Write-Host "Creating zava-api..."
    Invoke-Az containerapp create -g $resourceGroup -n "zava-api" --environment $containerAppsEnvironment --image $apiImage --registry-server $registryServer --registry-identity $identityId --user-assigned $identityId --target-port 8000 --ingress external --min-replicas 1 --max-replicas 2 --cpu 0.5 --memory "1.0Gi"
}

$apiFqdn = (& az containerapp show -g $resourceGroup -n "zava-api" --query properties.configuration.ingress.fqdn -o tsv)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($apiFqdn)) {
    throw "Unable to resolve zava-api FQDN"
}
$apiUrl = "https://$apiFqdn"

if (Test-ContainerAppExists -ResourceGroup $resourceGroup -Name "zava-mcp") {
    Write-Host "Updating zava-mcp..."
    Invoke-Az containerapp identity assign -g $resourceGroup -n "zava-mcp" --user-assigned $identityId
    Invoke-Az containerapp registry set -g $resourceGroup -n "zava-mcp" --server $registryServer --identity $identityId
    Invoke-Az containerapp update -g $resourceGroup -n "zava-mcp" --image $mcpImage --set-env-vars "ZAVA_API_BASE_URL=$apiUrl" --min-replicas 1 --max-replicas 2 --cpu 0.5 --memory "1.0Gi"
} else {
    Write-Host "Creating zava-mcp..."
    Invoke-Az containerapp create -g $resourceGroup -n "zava-mcp" --environment $containerAppsEnvironment --image $mcpImage --registry-server $registryServer --registry-identity $identityId --user-assigned $identityId --target-port 8080 --ingress external --min-replicas 1 --max-replicas 2 --cpu 0.5 --memory "1.0Gi" --env-vars "ZAVA_API_BASE_URL=$apiUrl"
}

$mcpFqdn = (& az containerapp show -g $resourceGroup -n "zava-mcp" --query properties.configuration.ingress.fqdn -o tsv)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($mcpFqdn)) {
    throw "Unable to resolve zava-mcp FQDN"
}
$mcpUrl = "https://$mcpFqdn/mcp"

Update-DotEnvValue -Path $EnvPath -Name "ZAVA_API_BASE_URL" -Value $apiUrl
Update-DotEnvValue -Path $EnvPath -Name "ZAVA_MCP_URL" -Value $mcpUrl

Write-Host ""
Write-Host "ZAVA_API_BASE_URL=$apiUrl"
Write-Host "ZAVA_MCP_URL=$mcpUrl"
