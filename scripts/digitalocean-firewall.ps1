[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Add", "Remove")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$FirewallId,
    [Parameter(Mandatory = $true)]
    [string]$RunnerIpv4,
    [uri]$ApiBaseUrl = [uri]"https://api.digitalocean.com"
)

$ErrorActionPreference = "Stop"

$parsedFirewallId = [guid]::Empty
if (-not [guid]::TryParse($FirewallId, [ref]$parsedFirewallId)) {
    throw "DigitalOcean firewall ID must be a UUID."
}

$parsedAddress = $null
if (
    -not [System.Net.IPAddress]::TryParse($RunnerIpv4, [ref]$parsedAddress) -or
    $parsedAddress.AddressFamily -ne [System.Net.Sockets.AddressFamily]::InterNetwork -or
    $RunnerIpv4 -cne $parsedAddress.ToString()
) {
    throw "Runner address must be one canonical IPv4 address."
}

if ($ApiBaseUrl.Scheme -ne "https" -and -not $ApiBaseUrl.IsLoopback) {
    throw "DigitalOcean API base URL must use HTTPS."
}

$token = $env:DIGITALOCEAN_TOKEN
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "DIGITALOCEAN_TOKEN is required."
}

$cidr = "$RunnerIpv4/32"
$payload = [ordered]@{
    inbound_rules = @(
        [ordered]@{
            protocol = "tcp"
            ports = "22"
            sources = [ordered]@{
                addresses = @($cidr)
            }
        }
    )
} | ConvertTo-Json -Depth 6 -Compress
$headers = @{
    Accept = "application/json"
    Authorization = "Bearer $token"
}
$firewallIdValue = $parsedFirewallId.ToString().ToLowerInvariant()
$endpoint = [uri]::new($ApiBaseUrl, "/v2/firewalls/$firewallIdValue/rules")
$method = if ($Action -eq "Add") { "Post" } else { "Delete" }

try {
    Invoke-RestMethod `
        -Uri $endpoint `
        -Method $method `
        -Headers $headers `
        -ContentType "application/json" `
        -Body $payload | Out-Null
}
catch {
    throw "DigitalOcean firewall rule request failed."
}

$result = if ($Action -eq "Add") { "added" } else { "removed" }
Write-Output "firewall_ssh_rule=$result cidr=$cidr"
