[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Verify", "Ensure")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$CheckId,
    [Parameter(Mandatory = $true)]
    [uri]$Target,
    [string]$AlertId,
    [uri]$ApiBaseUrl = [uri]"https://api.digitalocean.com",
    [switch]$AllowCreate
)

$ErrorActionPreference = "Stop"
$parsedCheckId = [guid]::Empty
if (-not [guid]::TryParse($CheckId, [ref]$parsedCheckId)) {
    throw "Uptime check ID must be a UUID."
}
$normalizedCheckId = $parsedCheckId.ToString().ToLowerInvariant()
if ($Target.Scheme -ne "https" -or $Target.UserInfo -or $Target.Fragment) {
    throw "Uptime target must be an HTTPS URL without credentials or fragment."
}
if ($ApiBaseUrl.Scheme -ne "https" -and -not $ApiBaseUrl.IsLoopback) {
    throw "DigitalOcean API base URL must use HTTPS."
}
$token = $env:DIGITALOCEAN_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "DIGITALOCEAN_TOKEN is required."
}
$headers = @{ Accept = "application/json"; Authorization = "Bearer $token" }
$checkEndpoint = [uri]::new($ApiBaseUrl, "/v2/uptime/checks/$normalizedCheckId")

try {
    $checkResponse = Invoke-RestMethod -Uri $checkEndpoint -Method Get -Headers $headers
}
catch {
    $statusCode = 0
    if ($null -ne $_.Exception.Response) {
        $statusCode = [int]$_.Exception.Response.StatusCode
    }
    if ($statusCode -ne 404 -or $Action -ne "Ensure" -or -not $AllowCreate) {
        throw "DigitalOcean Uptime check verification failed."
    }
    $payload = [ordered]@{
        name = "DevRadar HTTPS health"
        target = $Target.AbsoluteUri
        type = "https"
        regions = @("se_asia", "us_east", "eu_west")
        enabled = $true
    } | ConvertTo-Json -Depth 5 -Compress
    try {
        $created = Invoke-RestMethod -Uri ([uri]::new($ApiBaseUrl, "/v2/uptime/checks")) -Method Post -Headers $headers -ContentType "application/json" -Body $payload
        $createdId = [string]$created.check.id
        if ([string]::IsNullOrWhiteSpace($createdId)) { throw "Uptime create response did not include an ID." }
        Write-Output "uptime_check=created id=$createdId"
        exit 0
    }
    catch {
        throw "DigitalOcean Uptime check creation failed."
    }
}

if ($checkResponse.check.target -cne $Target.AbsoluteUri -or $checkResponse.check.type -cne "https" -or $checkResponse.check.enabled -ne $true) {
    throw "DigitalOcean Uptime check does not match the expected HTTPS target."
}
if (-not [string]::IsNullOrWhiteSpace($AlertId)) {
    $parsedAlertId = [guid]::Empty
    if (-not [guid]::TryParse($AlertId, [ref]$parsedAlertId)) { throw "Uptime alert ID must be a UUID." }
    $alertEndpoint = [uri]::new($ApiBaseUrl, "/v2/uptime/checks/$normalizedCheckId/alerts/$($parsedAlertId.ToString().ToLowerInvariant())")
    try { Invoke-RestMethod -Uri $alertEndpoint -Method Get -Headers $headers | Out-Null }
    catch { throw "DigitalOcean Uptime alert verification failed." }
    Write-Output "uptime_check=pass id=$normalizedCheckId alert=pass"
    exit 0
}
Write-Output "uptime_check=pass id=$normalizedCheckId"
