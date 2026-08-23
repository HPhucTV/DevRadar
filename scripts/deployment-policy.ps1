function Get-DeploymentEnvironmentValue {
    param([string]$Path, [string]$Name)
    $escapedName = [regex]::Escape($Name)
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match "^\s*$escapedName\s*=\s*(.*)\s*$") {
            return $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    return $null
}

function Assert-DeploymentPolicy {
    param(
        [string]$EnvironmentFile,
        [uri]$BaseUrl,
        [switch]$RequireHttps
    )

    $deploymentClassValue = Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_DEPLOYMENT_CLASS"
    $deploymentClass = if ([string]::IsNullOrWhiteSpace($deploymentClassValue)) {
        "LOCALHOST_SERVICE"
    }
    else {
        $deploymentClassValue.ToUpperInvariant()
    }
    $isProtected = $deploymentClass -in @("PROTECTED", "PUBLIC")
    if (-not $isProtected) {
        return
    }

    if ($BaseUrl.Scheme -ne "https" -or $RequireHttps.IsPresent -eq $false) {
        throw "Protected/public deployment requires an HTTPS smoke URL and -RequireHttps."
    }
    if ((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_AUTH_ENABLED") -ne "true") {
        throw "Protected/public deployment requires DEVRADAR_AUTH_ENABLED=true."
    }
    if ((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_AUTH_COOKIE_SECURE") -ne "true") {
        throw "Protected/public deployment requires a Secure auth cookie."
    }
    if ((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_SECRET_SOURCE") -ne "managed") {
        throw "Protected/public deployment requires DEVRADAR_SECRET_SOURCE=managed."
    }
    $origins = Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_ALLOWED_ORIGINS"
    if ([string]::IsNullOrWhiteSpace($origins) -or $origins -match "\*") {
        throw "Protected/public deployment requires an explicit CORS origin allow-list."
    }
    foreach ($origin in $origins.Split(',')) {
        if (-not $origin.Trim().StartsWith("https://", [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Protected/public deployment origins must all use HTTPS."
        }
    }
    if ([string]::IsNullOrWhiteSpace((Get-DeploymentEnvironmentValue $EnvironmentFile "DEVRADAR_OPERATOR_PASSWORD_HASH"))) {
        throw "Protected/public deployment requires a managed operator password hash."
    }
    if ((Get-DeploymentEnvironmentValue $EnvironmentFile "POSTGRES_PASSWORD") -eq "devradar_local_only") {
        throw "Protected/public deployment cannot use the local database password."
    }
}
