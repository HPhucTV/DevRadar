from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "start-devradar.cmd"
LAUNCHER = ROOT / "scripts" / "start-devradar.ps1"
COMPOSE = ROOT / "compose.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
WEB_SMOKE = ROOT / "scripts" / "web-smoke.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _run_launcher_functions(
    function_names: tuple[str, ...], body: str, *, timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh")
    assert powershell is not None, "PowerShell is required by the launcher contract"
    launcher_path = str(LAUNCHER).replace("'", "''")
    names = ", ".join(f'"{name}"' for name in function_names)
    script = f"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    '{launcher_path}',
    [ref]$tokens,
    [ref]$errors
)
if ($errors.Count -ne 0) {{ throw 'Launcher parse failed.' }}
$functionNames = @({names})
foreach ($functionName in $functionNames) {{
    $definition = $ast.Find(
        {{
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $functionName
        }},
        $true
    )
    if ($null -eq $definition) {{ throw "Missing function: $functionName" }}
    Invoke-Expression $definition.Extent.Text
}}
{body}
"""
    return subprocess.run(
        [powershell, "-NoLogo", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def test_one_click_cmd_calls_bounded_powershell_launcher() -> None:
    command = _read(CMD)

    assert "powershell.exe" in command
    assert "-NoProfile" in command
    assert "-ExecutionPolicy Bypass" in command
    assert "scripts\\start-devradar.ps1" in command
    assert "if errorlevel 1" in command.casefold()
    assert "pause" in command.casefold()


def test_launcher_creates_env_once_and_restores_process_environment() -> None:
    launcher = _read(LAUNCHER)

    assert "Get-Command docker" in launcher
    assert "$dockerExecutable --context $DockerContext compose version" in launcher
    assert "Test-Path -LiteralPath $environmentFile" in launcher
    assert "Copy-Item -LiteralPath $environmentExample" in launcher
    assert "finally" in launcher
    assert "[Environment]::SetEnvironmentVariable" in launcher
    for assignment in (
        '$env:DEVRADAR_AUTH_ENABLED = "false"',
        '$env:DEVRADAR_LOCAL_NO_LOGIN_ENABLED = "true"',
        '$env:DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED = "true"',
        '$env:DEVRADAR_OPERATOR_WRITE_ENABLED = "true"',
    ):
        assert assignment in launcher


def test_launcher_ensures_docker_engine_before_compose() -> None:
    launcher = _read(LAUNCHER)

    ensure_call = "Ensure-DockerEngine -TimeoutSeconds $DockerReadyTimeoutSeconds"
    compose_probe = "& $dockerExecutable --context $DockerContext compose version"
    assert "[ValidateRange(1, 900)]" in launcher
    assert "$DockerReadyTimeoutSeconds = 180" in launcher
    assert "function Test-DockerEngine" in launcher
    assert "Invoke-DockerCommand" in launcher
    assert ensure_call in launcher
    assert launcher.index(ensure_call) < launcher.index(compose_probe)


def test_launcher_discovers_starts_and_boundedly_waits_for_docker_desktop() -> None:
    launcher = _read(LAUNCHER)

    for contract in (
        "function Find-DockerDesktop",
        'Join-Path $env:ProgramFiles "Docker\\Docker\\Docker Desktop.exe"',
        'Join-Path $env:LOCALAPPDATA "Docker\\Docker Desktop.exe"',
        'Get-Process -Name "Docker Desktop"',
        "Start-Process -FilePath $dockerDesktopPath",
        "function Wait-DockerEngine",
        "Start-Sleep -Milliseconds $sleepMilliseconds",
        'throw "Docker Desktop did not become ready within $TimeoutSeconds seconds."',
    ):
        assert contract in launcher

    lowered = launcher.casefold()
    for forbidden in (
        "start-service",
        "stop-process",
        "--volumes",
        "crawl --",
        "enable source",
    ):
        assert forbidden not in lowered


def test_launcher_pins_every_docker_command_to_local_desktop_context() -> None:
    launcher = _read(LAUNCHER)

    assert '$DockerContext = "desktop-linux"' in launcher
    assert '$DockerDesktopEndpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"' in launcher
    assert "context inspect $DockerContext --format" in launcher
    assert "{{.Endpoints.docker.Host}}" in launcher
    assert "function Test-DockerDesktopContext" in launcher
    assert "does not point to local Docker Desktop" in launcher
    assert launcher.count("Get-Command docker -CommandType Application") == 3
    assert launcher.count("& $dockerExecutable --context $DockerContext compose") == 5
    assert "& docker compose" not in launcher


def test_bounded_process_terminates_a_hung_probe() -> None:
    completed = _run_launcher_functions(
        ("Invoke-BoundedProcess",),
        """
$childPowerShell = (Get-Process -Id $PID).Path
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$result = Invoke-BoundedProcess `
    -FilePath $childPowerShell `
    -Arguments '-NoLogo -NoProfile -Command "Start-Sleep -Seconds 5"' `
    -TimeoutMilliseconds 200
[pscustomobject]@{
    Completed = $result.Completed
    ElapsedMilliseconds = $stopwatch.ElapsedMilliseconds
} | ConvertTo-Json -Compress
""",
        timeout=4,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout.strip())
    assert payload["Completed"] is False
    assert payload["ElapsedMilliseconds"] < 1500


def test_bounded_process_does_not_wait_unbounded_after_timeout() -> None:
    launcher = _read(LAUNCHER)
    timeout_start = launcher.index("if (-not $process.WaitForExit($TimeoutMilliseconds)) {")
    timeout_return = launcher.index("return [pscustomobject]@{", timeout_start)

    assert "$process.WaitForExit()" not in launcher[timeout_start:timeout_return]


def test_desktop_context_rejects_a_remote_endpoint() -> None:
    completed = _run_launcher_functions(
        ("Test-DockerDesktopContext",),
        """
$script:DockerContext = "desktop-linux"
$script:DockerDesktopEndpoint = "npipe:////./pipe/dockerDesktopLinuxEngine"
function Invoke-DockerCommand {
    [pscustomobject]@{
        Completed = $true
        ExitCode = 0
        StandardOutput = "tcp://remote.example:2376"
        StandardError = ""
    }
}
try {
    [void](Test-DockerDesktopContext -TimeoutMilliseconds 100)
    throw "Remote endpoint was accepted."
}
catch {
    Write-Output $_.Exception.Message
}
""",
    )

    assert completed.returncode == 0, completed.stderr
    assert "does not point to local Docker Desktop" in completed.stdout


def test_launcher_builds_migrates_starts_smokes_then_opens_dashboard() -> None:
    launcher = _read(LAUNCHER)
    dashboard_open = 'Start-Process "http://127.0.0.1:3000"'

    assert "--profile crawler build api web crawler" in launcher
    assert "up -d database --wait" in launcher
    assert "run --rm api python -m alembic upgrade head" in launcher
    assert "--profile crawler up -d api web crawler --wait" in launcher
    assert "scripts\\smoke.ps1" in launcher
    assert "scripts\\web-smoke.ps1" in launcher
    assert dashboard_open in launcher
    assert launcher.index("scripts\\smoke.ps1") < launcher.index(dashboard_open)
    assert launcher.index("scripts\\web-smoke.ps1") < launcher.index(dashboard_open)
    assert "--volumes" not in launcher
    assert "crawl now" not in launcher.casefold()
    assert "enable source" not in launcher.casefold()


def test_compose_and_web_smoke_cover_local_recipe_worker() -> None:
    compose = _read(COMPOSE)
    environment = _read(ENV_EXAMPLE)
    smoke = _read(WEB_SMOKE)

    assert "source-recipe-worker" in compose
    assert "DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED=false" in environment
    assert "DEVRADAR_CUSTOM_SOURCE_POLL_SECONDS" not in environment
    assert '"/sources"' in smoke
    assert '"/api/devradar/privacy"' in smoke
    assert '"privacy-v2"' in smoke
    assert smoke.count("-UseBasicParsing") == 2
