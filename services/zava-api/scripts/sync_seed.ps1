$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$serviceRoot = Resolve-Path (Join-Path $scriptDir "..")
$repoRoot = Resolve-Path (Join-Path $scriptDir "..\..\..")
$source = Join-Path $repoRoot "data\structured\*.csv"
$dest = Join-Path $serviceRoot "app\seed"
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $dest
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item -Path $source -Destination $dest -Force
Write-Host "Synced canonical Zava apparel CSVs from data/structured to services/zava-api/app/seed."
