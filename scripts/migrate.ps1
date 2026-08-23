[CmdletBinding()]
param(
    [string]$EnvironmentFile = ".env.example",
    [string]$ProjectName = "devradar",
    [ValidateSet("check", "upgrade")]
    [string]$Action = "check"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file was not found: $EnvironmentFile"
}
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is required for migration commands."
}

$composeArgs = @(
    "compose",
    "--env-file", $EnvironmentFile,
    "--project-name", $ProjectName,
    "run", "--rm", "--no-deps", "api",
    "python", "-m", "alembic"
)
if ($Action -eq "upgrade") {
    $composeArgs += @("upgrade", "head")
}
else {
    $composeArgs += "check"
}

& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Migration action '$Action' failed with exit code $LASTEXITCODE."
}
Write-Output "migration=$Action"
