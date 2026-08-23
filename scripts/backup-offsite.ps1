[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Init", "Backup", "Restore", "Retain", "Check")]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$Repository,
    [string]$ArchivePath,
    [string]$RestorePath,
    [string]$ResticImage = "devradar-restic:local",
    [switch]$AllowLocalRepository
)

$ErrorActionPreference = "Stop"

$isLocalRepository = $Repository -match "^local:(.+)$"
$effectiveRepository = $Repository
if ($isLocalRepository) {
    if (-not $AllowLocalRepository) {
        throw "Local repositories require -AllowLocalRepository."
    }
}
else {
    if ($Repository -notmatch "^s3:https://") {
        throw "Production off-host repository must use an HTTPS S3-compatible URL."
    }
    if ($ResticImage -notmatch "@sha256:[0-9a-f]{64}$") {
        throw "Restic image must use an immutable sha256 digest."
    }
}

$passwordFile = $env:RESTIC_PASSWORD_FILE
if ([string]::IsNullOrWhiteSpace($passwordFile)) {
    throw "RESTIC_PASSWORD_FILE is required; do not pass a repository password as an argument."
}
if (-not (Test-Path -LiteralPath $passwordFile -PathType Leaf)) {
    throw "RESTIC_PASSWORD_FILE was not found."
}
if ($Action -eq "Backup" -and [string]::IsNullOrWhiteSpace($ArchivePath)) {
    throw "ArchivePath is required for Backup."
}
if ($Action -eq "Restore" -and [string]::IsNullOrWhiteSpace($RestorePath)) {
    throw "RestorePath is required for Restore."
}

$dockerArgs = @(
    "run", "--rm", "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
    "--env", "HOME=/tmp",
    "--env", "RESTIC_CACHE_DIR=/tmp/restic-cache",
    "--env", "RESTIC_PASSWORD_FILE=/run/secrets/restic-password",
    "--env", "AWS_ACCESS_KEY_ID",
    "--env", "AWS_SECRET_ACCESS_KEY",
    "--env", "AWS_SESSION_TOKEN",
    "--env", "AWS_DEFAULT_REGION",
    "--mount", "type=bind,source=$([System.IO.Path]::GetFullPath($passwordFile)),target=/run/secrets/restic-password,readonly"
)

if (-not $isLocalRepository) {
    foreach ($path in @("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($path))) {
            throw "$path is required for the off-host S3 repository."
        }
    }
}

if ($isLocalRepository) {
    $localRepository = [System.IO.Path]::GetFullPath($Matches[1])
    if (-not (Test-Path -LiteralPath $localRepository)) {
        New-Item -ItemType Directory -Path $localRepository | Out-Null
    }
    $dockerArgs += @("--mount", "type=bind,source=$localRepository,target=/repo")
    # Local Windows bind mounts may be owned by root from a previous Docker smoke; this explicit
    # test-only switch does not apply to the production S3 path.
    $dockerArgs += @("--user", "0:0")
    $effectiveRepository = "local:/repo"
}

if ($Action -eq "Init") {
    $command = @("$ResticImage", "-r", $effectiveRepository, "init")
}
elseif ($Action -eq "Backup") {
    $archive = [System.IO.Path]::GetFullPath($ArchivePath)
    if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
        throw "ArchivePath was not found."
    }
    $dockerArgs += @("--mount", "type=bind,source=$archive,target=/input/archive.dump,readonly")
    $command = @("$ResticImage", "-r", $effectiveRepository, "backup", "/input/archive.dump", "--tag", "devradar-postgresql")
}
elseif ($Action -eq "Restore") {
    $target = [System.IO.Path]::GetFullPath($RestorePath)
    if (-not (Test-Path -LiteralPath $target)) {
        New-Item -ItemType Directory -Path $target | Out-Null
    }
    $dockerArgs += @("--mount", "type=bind,source=$target,target=/output")
    $command = @("$ResticImage", "-r", $effectiveRepository, "restore", "latest", "--tag", "devradar-postgresql", "--target", "/output")
}
elseif ($Action -eq "Retain") {
    $command = @("$ResticImage", "-r", $effectiveRepository, "forget", "--keep-daily", "7", "--keep-weekly", "4", "--prune")
}
else {
    $command = @("$ResticImage", "-r", $effectiveRepository, "check")
}

$output = & docker ($dockerArgs + $command) 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Restic action failed: $Action."
}
Write-Output "offsite_backup=pass action=$Action"
