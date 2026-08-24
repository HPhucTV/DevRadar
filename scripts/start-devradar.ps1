[CmdletBinding()]
param()

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
    $null = Get-Command docker -ErrorAction Stop
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
    Write-Error "DevRadar could not start. Check Docker Desktop and the command output above."
    $exitCode = 1
}
finally {
    foreach ($name in $managedEnvironment) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
    }
    Pop-Location
}

exit $exitCode
