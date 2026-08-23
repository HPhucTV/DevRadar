import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BACKUP_SCRIPT = Path("scripts/backup-offsite.ps1")
UPTIME_SCRIPT = Path("scripts/digitalocean-uptime.ps1")
RESTIC_DOCKERFILE = Path("deploy/restic/Dockerfile")
BACKUP_WORKFLOW = Path(".github/workflows/backup-production.yml")
UPTIME_WORKFLOW = Path(".github/workflows/uptime-production.yml")
PRODUCTION_ENV = Path(".env.production.example")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pwsh() -> str:
    executable = shutil.which("pwsh")
    assert executable is not None
    return executable


def _run_pwsh(
    script: Path, *arguments: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_pwsh(), "-NoLogo", "-NoProfile", "-File", str(script), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_v6_014_scripts_and_workflows_lock_pinned_fail_closed_contract() -> None:
    backup = _read(BACKUP_SCRIPT)
    uptime = _read(UPTIME_SCRIPT)
    backup_workflow = _read(BACKUP_WORKFLOW)
    uptime_workflow = _read(UPTIME_WORKFLOW)
    env = _read(PRODUCTION_ENV)

    dockerfile = _read(RESTIC_DOCKERFILE)
    assert "golang:1.26.6-alpine3.23@sha256:e57c41c1" in dockerfile
    assert "restic-0.19.1.tar.gz" in dockerfile
    assert "bb9b1a19040744d26d8a79be029d4e6b189c45ccc9d8831d7fe367d3c33df725" in dockerfile
    assert "golang.org/x/net@v0.56.0" in dockerfile
    assert "golang.org/x/text@v0.39.0" in dockerfile
    assert "google.golang.org/grpc@v1.82.1" in dockerfile
    assert "FROM scratch" in dockerfile
    assert "USER 65532:65532" in dockerfile
    assert "ghcr.io/restic/restic" not in backup
    assert "RESTIC_PASSWORD_FILE" in backup
    assert '[ValidateSet("Init", "Backup", "Restore", "Retain", "Check")]' in backup
    assert "AWS_SECRET_ACCESS_KEY" in backup
    assert "source devradar-offsite.env" not in backup_workflow
    assert '"--keep-daily", "7"' in backup
    assert '"--keep-weekly", "4"' in backup
    assert "restic:latest" not in backup
    assert "DIGITALOCEAN_TOKEN" in uptime
    assert "/v2/uptime/checks" in uptime
    assert "https" in uptime
    assert "schedule:" in backup_workflow
    assert "workflow_dispatch:" in backup_workflow
    assert "if: always()" in backup_workflow
    assert "DEVRADAR_RESTIC_PASSWORD" in backup_workflow
    assert "docker login ghcr.io" in backup_workflow
    assert "docker logout ghcr.io" in backup_workflow
    assert '--user "$container_user"' in backup_workflow
    assert "workflow_dispatch:" in uptime_workflow
    assert "uptime:read" in uptime_workflow
    assert "DEVRADAR_UPTIME_CHECK_ID" in uptime_workflow
    assert "DEVRADAR_RESTIC_IMAGE=ghcr.io/hphuctv/devradar-restic@sha256:" in env
    assert "IMAGE_ROOT-restic" in backup_workflow


def test_offsite_backup_rejects_missing_password_before_docker(tmp_path: Path) -> None:
    archive = tmp_path / "database.dump"
    archive.write_bytes(b"custom-archive")
    repository = tmp_path / "repository"

    environment = os.environ.copy()
    environment.pop("RESTIC_PASSWORD", None)
    environment.pop("RESTIC_PASSWORD_FILE", None)
    result = _run_pwsh(
        BACKUP_SCRIPT,
        "-Action",
        "Backup",
        "-Repository",
        f"local:{repository}",
        "-ArchivePath",
        str(archive),
        "-AllowLocalRepository",
        env=environment,
    )

    assert result.returncode != 0
    assert "RESTIC_PASSWORD" in result.stderr
    assert "custom-archive" not in result.stdout + result.stderr


def test_offsite_backup_requires_action_specific_path(tmp_path: Path) -> None:
    password_file = tmp_path / "restic-password"
    password_file.write_text("local-only-password", encoding="utf-8")
    result = _run_pwsh(
        BACKUP_SCRIPT,
        "-Action",
        "Backup",
        "-Repository",
        f"local:{tmp_path / 'repository'}",
        "-AllowLocalRepository",
        env=dict(os.environ) | {"RESTIC_PASSWORD_FILE": str(password_file)},
    )

    assert result.returncode != 0
    assert "ArchivePath is required" in result.stderr


def test_allow_local_switch_does_not_bypass_remote_image_digest() -> None:
    result = _run_pwsh(
        BACKUP_SCRIPT,
        "-Action",
        "Check",
        "-Repository",
        "s3:https://sgp1.digitaloceanspaces.com/devradar-backups",
        "-ResticImage",
        "devradar-restic:local",
        "-AllowLocalRepository",
        env=dict(os.environ),
    )

    assert result.returncode != 0
    assert "immutable sha256 digest" in result.stderr


class _UptimeHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def do_GET(self) -> None:  # noqa: N802
        self.__class__.requests.append(("GET", self.path, None))
        body = json.dumps(
            {
                "check": {
                    "id": "22222222-2222-4222-8222-222222222222",
                    "target": "https://devradar.example.com/api/v1/health",
                    "enabled": True,
                    "type": "https",
                }
            }
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


def test_uptime_verify_uses_bounded_get_and_never_logs_token() -> None:
    _UptimeHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UptimeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = "test-digitalocean-token"
    try:
        result = _run_pwsh(
            UPTIME_SCRIPT,
            "-Action",
            "Verify",
            "-CheckId",
            "22222222-2222-4222-8222-222222222222",
            "-Target",
            "https://devradar.example.com/api/v1/health",
            "-ApiBaseUrl",
            f"http://127.0.0.1:{server.server_port}",
            env=os.environ | {"DIGITALOCEAN_TOKEN": token},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "uptime_check=pass id=22222222-2222-4222-8222-222222222222"
    assert token not in result.stdout + result.stderr
    assert _UptimeHandler.requests == [
        ("GET", "/v2/uptime/checks/22222222-2222-4222-8222-222222222222", None)
    ]
