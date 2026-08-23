[CmdletBinding()]
param(
    [string]$EnvironmentFile = ".env.example",
    [string]$ProjectName = "devradar",
    [Parameter(Mandatory = $true)]
    [string]$Image,
    [string]$WebImage = "devradar-web:local",
    [uri]$BaseUrl = [uri]"http://127.0.0.1:8000",
    [uri]$WebBaseUrl = [uri]"http://127.0.0.1:3000",
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
if ($WebImage -notmatch "^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?(?:@sha256:[0-9a-f]{64})?$") {
    throw "Web image reference contains unsupported characters."
}
Assert-DeploymentPolicy `
    -EnvironmentFile $EnvironmentFile `
    -BaseUrl $BaseUrl `
    -WebBaseUrl $WebBaseUrl `
    -RequireHttps:$RequireHttps
& docker image inspect $Image *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Rollback image '$Image' is not available locally. Pull it through the approved registry workflow first."
}
& docker image inspect $WebImage *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Rollback web image '$WebImage' is not available locally. Pull it through the approved registry workflow first."
}

$previousImage = $env:DEVRADAR_APP_IMAGE
$previousWebImage = $env:DEVRADAR_WEB_IMAGE
$env:DEVRADAR_APP_IMAGE = $Image
$env:DEVRADAR_WEB_IMAGE = $WebImage
try {
    & docker compose --env-file $EnvironmentFile --project-name $ProjectName up --detach api web --wait
    if ($LASTEXITCODE -ne 0) { throw "API/web rollback deployment failed." }
    & $PSScriptRoot\smoke.ps1 -BaseUrl $BaseUrl -RequireHttps:$RequireHttps
    & $PSScriptRoot\web-smoke.ps1 -BaseUrl $WebBaseUrl -RequireHttps:$RequireHttps
    Write-Output "rollback=pass api_image=$Image web_image=$WebImage project=$ProjectName"
}
finally {
    if ($null -eq $previousImage) {
        Remove-Item Env:DEVRADAR_APP_IMAGE -ErrorAction SilentlyContinue
    }
    else {
        $env:DEVRADAR_APP_IMAGE = $previousImage
    }
    if ($null -eq $previousWebImage) {
        Remove-Item Env:DEVRADAR_WEB_IMAGE -ErrorAction SilentlyContinue
    }
    else {
        $env:DEVRADAR_WEB_IMAGE = $previousWebImage
    }
}
