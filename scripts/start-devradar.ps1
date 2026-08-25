[CmdletBinding()]
param(
    [ValidateRange(1, 900)]
    [int]$DockerReadyTimeoutSeconds = 180
)

function Test-DockerEngine {
    & docker info --format "{{.ServerVersion}}" *> $null
    return $LASTEXITCODE -eq 0
}

function Find-DockerDesktop {
    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidates += Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates += Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe"
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    return $null
}

function Wait-DockerEngine {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    while ($stopwatch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-DockerEngine) {
            Write-Output "Docker Desktop is ready."
            return
        }

        $elapsedSeconds = [int][Math]::Floor($stopwatch.Elapsed.TotalSeconds)
        Write-Output "Waiting for Docker Desktop... $elapsedSeconds/$TimeoutSeconds seconds"
        $remainingSeconds = $TimeoutSeconds - $elapsedSeconds
        $sleepSeconds = [Math]::Min(5, [Math]::Max(1, $remainingSeconds))
        Start-Sleep -Seconds $sleepSeconds
    }

    if (Test-DockerEngine) {
        Write-Output "Docker Desktop is ready."
        return
    }
    throw "Docker Desktop did not become ready within $TimeoutSeconds seconds."
}

function Ensure-DockerEngine {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    if ($null -eq (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker CLI was not found. Install Docker Desktop, then run start-devradar.cmd again."
    }
    if (Test-DockerEngine) {
        Write-Output "Docker Desktop is already ready."
        return
    }

    $desktopProcesses = @(Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)
    if ($desktopProcesses.Count -eq 0) {
        $dockerDesktopPath = Find-DockerDesktop
        if ([string]::IsNullOrWhiteSpace($dockerDesktopPath)) {
            throw "Docker Desktop was not found in a supported install location. Install or open Docker Desktop, then run start-devradar.cmd again."
        }
        Write-Output "Opening Docker Desktop..."
        Start-Process -FilePath $dockerDesktopPath
    }
    else {
        Write-Output "Docker Desktop is running; waiting for its engine..."
    }

    Wait-DockerEngine -TimeoutSeconds $TimeoutSeconds
}

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$environmentExample = Join-Path $repositoryRoot ".env.example"
$environmentFile = Join-Path $repositoryRoot ".env"
$managedEnvironment = @(
    "DEVRADAR_AUTH_ENABLED",
    "DEVRADAR_LOCAL_NO_LOGIN_ENABLED",
    "DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED",
    "DEVRADAR_OPERATOR_WRITE_ENABLED"
)
$previousEnvironment = @{}
$exitCode = 0

foreach ($name in $managedEnvironment) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}

Push-Location $repositoryRoot
try {
    Ensure-DockerEngine -TimeoutSeconds $DockerReadyTimeoutSeconds
    Write-Output "Starting DevRadar..."
    & docker compose version
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose is unavailable."
    }

    if (-not (Test-Path -LiteralPath $environmentFile)) {
        Copy-Item -LiteralPath $environmentExample -Destination $environmentFile
    }

    $env:DEVRADAR_AUTH_ENABLED = "false"
    $env:DEVRADAR_LOCAL_NO_LOGIN_ENABLED = "true"
    $env:DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED = "true"
    $env:DEVRADAR_OPERATOR_WRITE_ENABLED = "true"

    & docker compose --env-file .env --profile crawler build api web crawler
    if ($LASTEXITCODE -ne 0) { throw "DevRadar image build failed." }

    & docker compose --env-file .env up -d database --wait
    if ($LASTEXITCODE -ne 0) { throw "DevRadar database startup failed." }

    & docker compose --env-file .env run --rm api python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "DevRadar migration failed." }

    & docker compose --env-file .env --profile crawler up -d api web crawler --wait
    if ($LASTEXITCODE -ne 0) { throw "DevRadar services did not become ready." }

    & (Join-Path $repositoryRoot "scripts\smoke.ps1") -BaseUrl "http://127.0.0.1:8000"
    & (Join-Path $repositoryRoot "scripts\web-smoke.ps1") -BaseUrl "http://127.0.0.1:3000"

    Start-Process "http://127.0.0.1:3000"
    Write-Output "DevRadar is ready at http://127.0.0.1:3000"
}
catch {
    Write-Error ("DevRadar could not start: {0}" -f $_.Exception.Message)
    $exitCode = 1
}
finally {
    foreach ($name in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    Pop-Location
}

exit $exitCode
