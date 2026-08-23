[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$EnvironmentFile,
    [Parameter(Mandatory = $true)]
    [string]$Domain
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "deployment-policy.ps1")

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file was not found: $EnvironmentFile"
}

$normalizedDomain = $Domain.Trim().ToLowerInvariant()
$domainPattern = "^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
if ($Domain -cne $normalizedDomain -or $normalizedDomain -notmatch $domainPattern) {
    throw "Production domain must be one lowercase DNS hostname."
}

$configuredDomain = Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_DOMAIN"
if ($configuredDomain -cne $normalizedDomain) {
    throw "Production domain does not match DEVRADAR_DOMAIN."
}
if ((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_DEPLOYMENT_CLASS") -cne "PUBLIC") {
    throw "Production environment requires DEVRADAR_DEPLOYMENT_CLASS=PUBLIC."
}
$expectedOrigin = "https://$normalizedDomain"
if ((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_ALLOWED_ORIGINS") -cne $expectedOrigin) {
    throw "Production CORS origin must exactly match the HTTPS domain."
}
if ([string]::IsNullOrWhiteSpace((Get-DeploymentEnvironmentValue $EnvironmentFile "POSTGRES_PASSWORD"))) {
    throw "Production database password must come from the managed secret."
}

$digestImagePattern = "^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
foreach ($imageVariable in @("DEVRADAR_APP_IMAGE", "DEVRADAR_CRAWLER_IMAGE", "DEVRADAR_WEB_IMAGE")) {
    $image = Get-DeploymentEnvironmentValue $EnvironmentFile $imageVariable
    if ([string]::IsNullOrWhiteSpace($image) -or $image -cnotmatch $digestImagePattern) {
        throw "Production image '$imageVariable' must use an immutable sha256 digest."
    }
}

$baseUrl = [uri]$expectedOrigin
Assert-DeploymentPolicy `
    -EnvironmentFile $EnvironmentFile `
    -BaseUrl $baseUrl `
    -WebBaseUrl $baseUrl `
    -RequireHttps

Write-Output "production_config=pass domain=$normalizedDomain"
