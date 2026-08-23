[CmdletBinding()]
param(
    [uri]$BaseUrl = [uri]"http://127.0.0.1:8000",
    [ValidateRange(1, 60)]
    [int]$Attempts = 12,
    [ValidateRange(1, 30)]
    [int]$DelaySeconds = 2,
    [switch]$RequireHttps
)

$ErrorActionPreference = "Stop"

if ($RequireHttps -and $BaseUrl.Scheme -ne "https") {
    throw "HTTPS is required for this deployment smoke: $BaseUrl"
}

$healthUri = [uri]::new($BaseUrl, "/api/v1/health")
$lastError = $null
for ($attempt = 1; $attempt -le $Attempts; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri $healthUri -Method Get -TimeoutSec 5
        if ($response.data.status -ne "ok") {
            throw "Health payload did not report status=ok."
        }
        Write-Output "smoke=pass endpoint=$healthUri"
        exit 0
    }
    catch {
        $lastError = $_.Exception.Message
        if ($attempt -lt $Attempts) {
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

throw "Health smoke failed after $Attempts attempts: $lastError"
