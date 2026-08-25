[CmdletBinding()]
param(
    [ValidateRange(1, 900)]
    [int]$DockerReadyTimeoutSeconds = 180
)

$DockerContext = "desktop-linux"
$DockerDesktopEndpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"

function Invoke-BoundedProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string]$Arguments,
        [Parameter(Mandatory = $true)]
        [ValidateRange(1, 900000)]
        [int]$TimeoutMilliseconds
    )

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = $Arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Failed to start Docker CLI."
        }
        $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
        $standardErrorTask = $process.StandardError.ReadToEndAsync()

        if (-not $process.WaitForExit($TimeoutMilliseconds)) {
            try {
                $process.Kill()
            }
            catch [System.InvalidOperationException] {
                # The process exited between the timeout and the kill request.
            }
            [void]$process.WaitForExit(1000)
            return [pscustomobject]@{
                Completed = $false
                ExitCode = $null
                StandardOutput = ""
                StandardError = ""
            }
        }

        $process.WaitForExit()
        return [pscustomobject]@{
            Completed = $true
            ExitCode = $process.ExitCode
            StandardOutput = $standardOutputTask.Result
            StandardError = $standardErrorTask.Result
        }
    }
    finally {
        $process.Dispose()
    }
}

function Invoke-DockerCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Arguments,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutMilliseconds
    )

    $dockerApplication = Get-Command docker -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
    return Invoke-BoundedProcess `
        -FilePath $dockerApplication.Source `
        -Arguments $Arguments `
        -TimeoutMilliseconds $TimeoutMilliseconds
}

function Test-DockerDesktopContext {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutMilliseconds
    )

    $arguments = "context inspect $DockerContext --format `"{{.Endpoints.docker.Host}}`""
    $result = Invoke-DockerCommand `
        -Arguments $arguments `
        -TimeoutMilliseconds $TimeoutMilliseconds
    if (-not $result.Completed -or $result.ExitCode -ne 0) {
        return $false
    }

    $endpoint = $result.StandardOutput.Trim()
    if ([string]::IsNullOrWhiteSpace($endpoint)) {
        return $false
    }
    if (-not [string]::Equals(
            $endpoint,
            $DockerDesktopEndpoint,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
        throw "Docker context '$DockerContext' does not point to local Docker Desktop. Reset Docker Desktop context, then run start-devradar.cmd again."
    }
    return $true
}

function Test-DockerEngine {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutMilliseconds
    )

    $arguments = "--context $DockerContext info --format `"{{.ServerVersion}}`""
    $result = Invoke-DockerCommand `
        -Arguments $arguments `
        -TimeoutMilliseconds $TimeoutMilliseconds
    return $result.Completed -and $result.ExitCode -eq 0
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
        [DateTime]$DeadlineUtc,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    while ([DateTime]::UtcNow -lt $DeadlineUtc) {
        $remainingMilliseconds = [int][Math]::Floor(
            ($DeadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
        )
        if ($remainingMilliseconds -le 0) {
            break
        }

        $probeTimeoutMilliseconds = [Math]::Min(5000, $remainingMilliseconds)
        if (Test-DockerDesktopContext -TimeoutMilliseconds $probeTimeoutMilliseconds) {
            $remainingMilliseconds = [int][Math]::Floor(
                ($DeadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
            )
            if (
                $remainingMilliseconds -gt 0 -and
                (Test-DockerEngine -TimeoutMilliseconds (
                        [Math]::Min(5000, $remainingMilliseconds)
                    ))
            ) {
                Write-Output "Docker Desktop is ready."
                return
            }
        }

        $remainingMilliseconds = [int][Math]::Floor(
            ($DeadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
        )
        if ($remainingMilliseconds -le 0) {
            break
        }
        $elapsedSeconds = [Math]::Max(
            0,
            $TimeoutSeconds - [int][Math]::Ceiling($remainingMilliseconds / 1000)
        )
        Write-Output "Waiting for Docker Desktop... $elapsedSeconds/$TimeoutSeconds seconds"
        $sleepMilliseconds = [Math]::Min(5000, $remainingMilliseconds)
        Start-Sleep -Milliseconds $sleepMilliseconds
    }
    throw "Docker Desktop did not become ready within $TimeoutSeconds seconds."
}

function Ensure-DockerEngine {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    if ($null -eq (
            Get-Command docker -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
        )) {
        throw "Docker CLI was not found. Install Docker Desktop, then run start-devradar.cmd again."
    }

    $deadlineUtc = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $initialTimeoutMilliseconds = [Math]::Min(5000, $TimeoutSeconds * 1000)
    if (Test-DockerDesktopContext -TimeoutMilliseconds $initialTimeoutMilliseconds) {
        $remainingMilliseconds = [int][Math]::Floor(
            ($deadlineUtc - [DateTime]::UtcNow).TotalMilliseconds
        )
        if (
            $remainingMilliseconds -gt 0 -and
            (Test-DockerEngine -TimeoutMilliseconds (
                    [Math]::Min(5000, $remainingMilliseconds)
                ))
        ) {
            Write-Output "Docker Desktop is already ready."
            return
        }
    }
    if ([DateTime]::UtcNow -ge $deadlineUtc) {
        throw "Docker Desktop did not become ready within $TimeoutSeconds seconds."
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

    Wait-DockerEngine -DeadlineUtc $deadlineUtc -TimeoutSeconds $TimeoutSeconds
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
    $dockerExecutable = (
        Get-Command docker -CommandType Application -ErrorAction Stop |
            Select-Object -First 1
    ).Source
    Write-Output "Starting DevRadar..."
    & $dockerExecutable --context $DockerContext compose version
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

    & $dockerExecutable --context $DockerContext compose --env-file .env --profile crawler build api web crawler
    if ($LASTEXITCODE -ne 0) { throw "DevRadar image build failed." }

    & $dockerExecutable --context $DockerContext compose --env-file .env up -d database --wait
    if ($LASTEXITCODE -ne 0) { throw "DevRadar database startup failed." }

    & $dockerExecutable --context $DockerContext compose --env-file .env run --rm api python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw "DevRadar migration failed." }

    & $dockerExecutable --context $DockerContext compose --env-file .env --profile crawler up -d api web crawler --wait
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
