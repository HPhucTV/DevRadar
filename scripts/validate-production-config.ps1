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

$environmentLines = @(Get-Content -LiteralPath $EnvironmentFile)
$criticalVariables = @(
    "DEVRADAR_DOMAIN",
    "DEVRADAR_DEPLOYMENT_CLASS",
    "DEVRADAR_SECRET_SOURCE",
    "DEVRADAR_AUTH_ENABLED",
    "DEVRADAR_AUTH_COOKIE_SECURE",
    "DEVRADAR_ALLOWED_ORIGINS",
    "DEVRADAR_OPERATOR_PASSWORD_HASH",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "DEVRADAR_DATABASE_IMAGE",
    "DEVRADAR_APP_IMAGE",
    "DEVRADAR_CRAWLER_IMAGE",
    "DEVRADAR_WEB_IMAGE",
    "DEVRADAR_INGRESS_IMAGE"
)
foreach ($variable in $criticalVariables) {
    $assignmentPattern = "^\s*$([regex]::Escape($variable))\s*="
    $assignments = @($environmentLines | Where-Object { $_ -match $assignmentPattern })
    if ($assignments.Count -ne 1) {
        throw "Production environment requires exactly one '$variable' assignment."
    }
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
$passwordHashLines = @(
    $environmentLines | Where-Object { $_ -match "^\s*DEVRADAR_OPERATOR_PASSWORD_HASH\s*=" }
)
$passwordHashPattern = '^\s*DEVRADAR_OPERATOR_PASSWORD_HASH\s*=\s*''pbkdf2_sha256\$[1-9][0-9]{5,}\$[A-Za-z0-9_-]{22}\$[A-Za-z0-9_-]{43}''\s*$'
if ($passwordHashLines.Count -ne 1 -or $passwordHashLines[0] -cnotmatch $passwordHashPattern) {
    throw "Production operator hash must be one single-quoted PBKDF2 value."
}
if ([string]::IsNullOrWhiteSpace((Get-DeploymentEnvironmentValue $EnvironmentFile "POSTGRES_PASSWORD"))) {
    throw "Production database password must come from the managed secret."
}

$digestImagePattern = "^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
foreach (
    $imageVariable in @(
        "DEVRADAR_DATABASE_IMAGE",
        "DEVRADAR_APP_IMAGE",
        "DEVRADAR_CRAWLER_IMAGE",
        "DEVRADAR_WEB_IMAGE",
        "DEVRADAR_INGRESS_IMAGE"
    )
) {
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
