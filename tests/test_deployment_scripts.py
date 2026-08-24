from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD = ROOT / "start-devradar.cmd"
LAUNCHER = ROOT / "scripts" / "start-devradar.ps1"
COMPOSE = ROOT / "compose.yaml"
ENV_EXAMPLE = ROOT / ".env.example"
WEB_SMOKE = ROOT / "scripts" / "web-smoke.ps1"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
    assert "docker compose version" in launcher
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


def test_launcher_builds_migrates_starts_smokes_then_opens_dashboard() -> None:
    launcher = _read(LAUNCHER)

    assert "--profile crawler build api web crawler" in launcher
    assert "up -d database --wait" in launcher
    assert "run --rm api python -m alembic upgrade head" in launcher
    assert "--profile crawler up -d api web crawler --wait" in launcher
    assert "scripts\\smoke.ps1" in launcher
    assert "scripts\\web-smoke.ps1" in launcher
    assert 'Start-Process "http://127.0.0.1:3000"' in launcher
    assert launcher.index("scripts\\smoke.ps1") < launcher.index("Start-Process")
    assert launcher.index("scripts\\web-smoke.ps1") < launcher.index("Start-Process")
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
