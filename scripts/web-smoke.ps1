[CmdletBinding()]
param(
    [uri]$BaseUrl = [uri]"http://127.0.0.1:3000",
    [switch]$RequireHttps,
    [ValidateRange(1, 60)]
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = "Stop"

if ($RequireHttps.IsPresent -and $BaseUrl.Scheme -ne "https") {
    throw "HTTPS is required for this web smoke target: $BaseUrl"
}

$loginUri = [uri]::new($BaseUrl, "/login")
$login = Invoke-WebRequest -Uri $loginUri -Method Get -TimeoutSec $TimeoutSeconds
if ($login.StatusCode -ne 200 -or $login.Content -notmatch "DevRadar") {
    throw "DevRadar web login smoke failed."
}

$privacyUri = [uri]::new($BaseUrl, "/api/devradar/privacy")
$privacy = Invoke-RestMethod -Uri $privacyUri -Method Get -TimeoutSec $TimeoutSeconds
if ($privacy.data.policyVersion -ne "privacy-v1") {
    throw "DevRadar web privacy BFF smoke failed."
}

$origin = $BaseUrl.GetLeftPart([System.UriPartial]::Authority)
Write-Output "web_smoke=pass base_url=$origin"
