[CmdletBinding()]
param(
    [string]$EnvironmentFile = ".env.example",
    [string]$ProjectName = "devradar",
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [uri]$BaseUrl = [uri]"http://127.0.0.1:8000",
    [switch]$RequireHttps
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "deployment-policy.ps1")

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file was not found: $EnvironmentFile"
}
if ($Image -notmatch "^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?(?:@sha256:[0-9a-f]{64})?$") {
    throw "Image reference contains unsupported characters."
}
Assert-DeploymentPolicy -EnvironmentFile $EnvironmentFile -BaseUrl $BaseUrl -RequireHttps:$RequireHttps
& docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Rollback image '$Image' is not available locally. Pull it through the approved registry workflow first."
}

$previousImage = $env:DEVRADAR_APP_IMAGE
$env:DEVRADAR_APP_IMAGE = $Image
try {
    & docker compose --env-file $EnvironmentFile --project-name $ProjectName up --detach api --wait
    if ($LASTEXITCODE -ne 0) { throw "API rollback deployment failed." }
    & $PSScriptRoot\smoke.ps1 -BaseUrl $BaseUrl -RequireHttps:$RequireHttps
    Write-Output "rollback=pass image=$Image project=$ProjectName"
}
finally {
    if ($null -eq $previousImage) {
        Remove-Item Env:DEVRADAR_APP_IMAGE -ErrorAction SilentlyContinue
    }
    else {
        $env:DEVRADAR_APP_IMAGE = $previousImage
    }
}
