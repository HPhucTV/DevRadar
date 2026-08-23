[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BackupPath,
    [string]$EnvironmentFile = ".env.example",
    [string]$ProjectName = "devradar",
    [string]$RestoreDatabase = ("devradar_restore_{0}" -f ([guid]::NewGuid().ToString("N").Substring(0, 12))),
    [switch]$KeepDatabase
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "docker-stream.ps1")

if (-not (Test-Path -LiteralPath $BackupPath)) {
    throw "Backup file was not found: $BackupPath"
}
if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
    throw "Environment file was not found: $EnvironmentFile"
}
if ($RestoreDatabase -notmatch "^[a-z_][a-z0-9_]{0,62}$") {
    throw "Restore database name contains unsupported characters."
}

$backup = [System.IO.Path]::GetFullPath($BackupPath)
$baseArgs = @("compose", "--env-file", $EnvironmentFile, "--project-name", $ProjectName, "exec", "-T", "database", "sh", "-c")
$createCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" createdb --username="$POSTGRES_USER" "' + $RestoreDatabase + '"'
$createArgs = $baseArgs + @($createCommand)
& docker @createArgs *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Could not create restore database."
}

$created = $true
try {
    $restoreCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore --username="$POSTGRES_USER" --dbname="' + $RestoreDatabase + '" --no-owner --exit-on-error'
    $restoreArgs = $baseArgs + @($restoreCommand)
    $result = Invoke-DockerInputFromFile -Arguments $restoreArgs -InputPath $backup
    if ($result.ExitCode -ne 0) {
        throw "PostgreSQL restore failed: $($result.Error.Trim())"
    }

    $checkCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" psql --username="$POSTGRES_USER" --dbname="' + $RestoreDatabase + '" --tuples-only --no-align --command="SELECT to_regclass(''public.alembic_version'') IS NOT NULL"'
    $checkArgs = $baseArgs + @($checkCommand)
    $check = (& docker @checkArgs 2>$null | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $check -ne "t") {
        throw "Restore verification did not find the Alembic version table."
    }
    Write-Output "restore=pass database=$RestoreDatabase"
}
finally {
    if ($created -and -not $KeepDatabase) {
        $dropCommand = 'PGPASSWORD="$POSTGRES_PASSWORD" dropdb --username="$POSTGRES_USER" --if-exists "' + $RestoreDatabase + '"'
        $dropArgs = $baseArgs + @($dropCommand)
        & docker @dropArgs *> $null
    }
}
