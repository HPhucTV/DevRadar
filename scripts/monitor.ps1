[CmdletBinding()]
param(
    [uri]$BaseUrl = [uri]"http://127.0.0.1:8000",
    [ValidateRange(1, 60000)]
    [int]$MaxLatencyMs = 2000,
    [switch]$RequireHttps
)

$ErrorActionPreference = "Stop"
if ($RequireHttps -and $BaseUrl.Scheme -ne "https") {
    throw "HTTPS is required for this monitor target."
}

$endpoint = [uri]::new($BaseUrl, "/api/v1/health")
$watch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    $response = Invoke-RestMethod -Uri $endpoint -Method Get -TimeoutSec 10
    $watch.Stop()
    $latency = [math]::Round($watch.Elapsed.TotalMilliseconds, 3)
    $ok = $response.data.status -eq "ok" -and $latency -le $MaxLatencyMs
    $event = [ordered]@{
        event = "devradar_health_probe"
        timestamp = [DateTime]::UtcNow.ToString("o")
        endpoint = $endpoint.AbsoluteUri
        status = if ($response.data.status -eq "ok") { "ok" } else { "degraded" }
        latencyMs = $latency
        thresholdMs = $MaxLatencyMs
    }
    $json = $event | ConvertTo-Json -Compress
    if ($ok) {
        Write-Output $json
        exit 0
    }
    [Console]::Error.WriteLine($json)
    exit 1
}
catch {
    $watch.Stop()
    $event = [ordered]@{
        event = "devradar_health_probe"
        timestamp = [DateTime]::UtcNow.ToString("o")
        endpoint = $endpoint.AbsoluteUri
        status = "unavailable"
        latencyMs = [math]::Round($watch.Elapsed.TotalMilliseconds, 3)
        error = "health_request_failed"
    }
    [Console]::Error.WriteLine(($event | ConvertTo-Json -Compress))
    exit 1
}
