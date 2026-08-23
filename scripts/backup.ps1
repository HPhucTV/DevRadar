[CmdletBinding()]
param(
    [string]$EnvironmentFile = ".env.example",
    [string]$ProjectName = "devradar",
    [string]$OutputPath = (Join-Path "backups" ("devradar-{0}.dump" -f (Get-Date -Format "yyyyMMdd-HHmmss")))
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "docker-stream.ps1")

if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file was not found: $EnvironmentFile"
}
$output = [System.IO.Path]::GetFullPath($OutputPath)
$parent = Split-Path -Parent $output
if (-not (Test-Path -LiteralPath $parent)) {
    New-Item -ItemType Directory -Path $parent | Out-Null
}

$args = @(
    "compose", "--env-file", $EnvironmentFile, "--project-name", $ProjectName,
    "exec", "-T", "database", "sh", "-c",
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump --username="$POSTGRES_USER" --dbname="$POSTGRES_DB" --format=custom --no-owner --no-privileges'
)
$result = Invoke-DockerOutputToFile -Arguments $args -OutputPath $output
if ($result.ExitCode -ne 0) {
    Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue
    throw "PostgreSQL backup failed: $($result.Error.Trim())"
}
$length = (Get-Item -LiteralPath $output).Length
if ($length -lt 128) {
    Remove-Item -LiteralPath $output -Force -ErrorAction SilentlyContinue
    throw "PostgreSQL backup was unexpectedly small."
}
Write-Output "backup=pass bytes=$length path=$output"
