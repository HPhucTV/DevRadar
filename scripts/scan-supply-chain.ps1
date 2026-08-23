param(
    [string]$Image = "devradar-app:local",
    [string]$EnvFile = ".env.example"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvFile)) {
    throw "Environment template was not found: $EnvFile"
}
if (-not (Test-Path -LiteralPath "web/package-lock.json")) {
    throw "web/package-lock.json is required for reproducible npm installs."
}

Push-Location web
try {
    npm audit --audit-level=high
    if ($LASTEXITCODE -ne 0) { throw "npm audit reported a high/critical finding." }
}
finally {
    Pop-Location
}

& ".venv\Scripts\python.exe" -m pip check
if ($LASTEXITCODE -ne 0) { throw "pip check failed." }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required for the container scan."
}
docker scout cves --only-severity critical,high --exit-code $Image
if ($LASTEXITCODE -eq 2) { throw "Docker Scout reported critical/high vulnerabilities." }
if ($LASTEXITCODE -ne 0) { throw "Docker Scout could not complete the container scan." }

Write-Output "supply_chain_scan=pass"
