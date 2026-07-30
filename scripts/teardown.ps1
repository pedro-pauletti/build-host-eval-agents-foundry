<#
.SYNOPSIS
  Tear down the Zava Foundry demo. Deletes the rg-zava-demo resource group and all
  resources in it (Foundry account/project, models, AI Search, ACR, Container Apps,
  App Insights). Does NOT touch the Fabric workspace (Zava-Demos).

.EXAMPLE
  ./scripts/teardown.ps1
  ./scripts/teardown.ps1 -ResourceGroup rg-zava-demo -Force
#>
[CmdletBinding()]
param(
  [string]$ResourceGroup = 'rg-zava-demo',
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

$exists = az group exists --name $ResourceGroup
if ($exists -ne 'true') {
  Write-Host "Resource group '$ResourceGroup' does not exist. Nothing to do." -ForegroundColor Yellow
  return
}

if (-not $Force) {
  Write-Host "This will DELETE resource group '$ResourceGroup' and ALL resources in it." -ForegroundColor Red
  $confirm = Read-Host "Type the resource group name to confirm"
  if ($confirm -ne $ResourceGroup) { Write-Host "Aborted."; return }
}

Write-Host "Deleting '$ResourceGroup' (running in background) ..." -ForegroundColor Cyan
az group delete --name $ResourceGroup --yes --no-wait
Write-Host "Delete requested. Also remember to remove the Foundry agents/toolbox, the Fabric" -ForegroundColor Yellow
Write-Host "Data Agent, and any Teams/Bot registrations if you created them." -ForegroundColor Yellow
