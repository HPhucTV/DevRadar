import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

PRODUCTION_COMPOSE = Path("compose.production.yaml")
CADDYFILE = Path("deploy/Caddyfile")
PRODUCTION_ENV = Path(".env.production.example")
WORKFLOW = Path(".github/workflows/deploy-production.yml")
CI = Path(".github/workflows/ci.yml")
VALIDATE_CONFIG = Path("scripts/validate-production-config.ps1")
FIREWALL = Path("scripts/digitalocean-firewall.ps1")
TEST_FIREWALL_ID = "11111111-1111-4111-8111-111111111111"
TEST_RUNNER_IP = "203.0.113.7"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _pwsh() -> str:
    executable = shutil.which("pwsh")
    assert executable is not None, "PowerShell 7 is required by the verified project commands"
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


def _write_production_env(
    path: Path,
    *,
    password: str,
    operator_hash: str,
) -> None:
    digest = "a" * 64
    path.write_text(
        "\n".join(
            (
                "DEVRADAR_DOMAIN=devradar.example.com",
                "DEVRADAR_DEPLOYMENT_CLASS=PUBLIC",
                "DEVRADAR_SECRET_SOURCE=managed",
                "DEVRADAR_AUTH_ENABLED=true",
                "DEVRADAR_AUTH_COOKIE_SECURE=true",
                "DEVRADAR_ALLOWED_ORIGINS=https://devradar.example.com",
                f"DEVRADAR_OPERATOR_PASSWORD_HASH={operator_hash}",
                "POSTGRES_DB=devradar",
                "POSTGRES_USER=devradar",
                f"POSTGRES_PASSWORD={password}",
                f"DEVRADAR_APP_IMAGE=ghcr.io/hphuctv/devradar-api@sha256:{digest}",
                f"DEVRADAR_CRAWLER_IMAGE=ghcr.io/hphuctv/devradar-crawler@sha256:{digest}",
                f"DEVRADAR_WEB_IMAGE=ghcr.io/hphuctv/devradar-web@sha256:{digest}",
                "",
            )
        ),
        encoding="utf-8",
    )


class _FirewallApiHandler(BaseHTTPRequestHandler):
    requests: list[tuple[str, dict[str, object]]] = []

    def _record(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        payload = cast(dict[str, object], json.loads(body))
        self.requests.append((self.command, payload))
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self._record()

    def do_DELETE(self) -> None:  # noqa: N802
        self._record()

    def log_message(self, format: str, *args: object) -> None:
        return


def test_production_ingress_is_single_host_pinned_and_hardened() -> None:
    compose = _read(PRODUCTION_COMPOSE)
    caddyfile = _read(CADDYFILE)

    assert "caddy:2.10.2-alpine@sha256:4c6e91c6" in compose
    assert '"${DEVRADAR_HTTP_HOST_PORT:-80}:80"' in compose
    assert '"${DEVRADAR_HTTPS_HOST_PORT:-443}:443"' in compose
    assert '"${DEVRADAR_HTTPS_HOST_PORT:-443}:443/udp"' in compose
    assert "read_only: true" in compose
    assert "NET_BIND_SERVICE" in compose
    assert "{$DEVRADAR_DOMAIN}" in caddyfile
    assert "handle /api/v1/*" in caddyfile
    assert "reverse_proxy api:8000" in caddyfile
    assert "reverse_proxy web:3000" in caddyfile


def test_production_example_is_public_managed_and_secret_free() -> None:
    env = _read(PRODUCTION_ENV)

    assert "DEVRADAR_DEPLOYMENT_CLASS=PUBLIC" in env
    assert "DEVRADAR_SECRET_SOURCE=managed" in env
    assert "DEVRADAR_AUTH_ENABLED=true" in env
    assert "DEVRADAR_AUTH_COOKIE_SECURE=true" in env
    assert "POSTGRES_PASSWORD=" in env
    assert "DEVRADAR_OPERATOR_PASSWORD_HASH=" in env
    assert "devradar_local_only" not in env
    assert "sk-" not in env


def test_production_workflow_is_manual_exact_sha_and_digest_only() -> None:
    workflow = _read(WORKFLOW)
    ci = _read(CI)

    assert "workflow_dispatch:" in workflow
    assert "release_sha:" in workflow
    assert "environment:" in workflow
    assert "name: production" in workflow
    assert "actions: read" in workflow
    assert "packages: write" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "validate-production-config.ps1" in workflow
    assert "digitalocean-firewall.ps1" in workflow
    assert "if: always()" in workflow
    assert "@sha256:" in workflow
    assert "password-stdin" in workflow
    assert "compose.production.yaml" in ci
    assert "devradar-ingress" in ci


def test_production_config_rejects_missing_managed_secrets(tmp_path: Path) -> None:
    environment_file = tmp_path / "production.env"
    _write_production_env(environment_file, password="", operator_hash="")

    result = _run_pwsh(
        VALIDATE_CONFIG,
        "-EnvironmentFile",
        str(environment_file),
        "-Domain",
        "devradar.example.com",
    )

    assert result.returncode != 0
    assert "production_config=pass" not in result.stdout


def test_production_config_accepts_managed_exact_digest_fixture(tmp_path: Path) -> None:
    environment_file = tmp_path / "production.env"
    password = "managed-test-password"
    operator_hash = "managed-test-hash"
    _write_production_env(
        environment_file,
        password=password,
        operator_hash=operator_hash,
    )

    result = _run_pwsh(
        VALIDATE_CONFIG,
        "-EnvironmentFile",
        str(environment_file),
        "-Domain",
        "devradar.example.com",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "production_config=pass domain=devradar.example.com"
    assert password not in result.stdout + result.stderr
    assert operator_hash not in result.stdout + result.stderr


def test_firewall_rejects_unbounded_ip_before_request() -> None:
    token = "test-digitalocean-token"
    result = _run_pwsh(
        FIREWALL,
        "-Action",
        "Add",
        "-FirewallId",
        TEST_FIREWALL_ID,
        "-RunnerIpv4",
        "127.0.0.1;whoami",
        "-ApiBaseUrl",
        "http://127.0.0.1:9",
        env=os.environ | {"DIGITALOCEAN_TOKEN": token},
    )

    assert result.returncode != 0
    assert token not in result.stdout + result.stderr


def test_firewall_add_remove_send_only_exact_ssh_rule() -> None:
    _FirewallApiHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FirewallApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = "test-digitalocean-token"
    api_base_url = f"http://127.0.0.1:{server.server_port}"
    expected_rule: dict[str, object] = {
        "inbound_rules": [
            {
                "protocol": "tcp",
                "ports": "22",
                "sources": {"addresses": [f"{TEST_RUNNER_IP}/32"]},
            }
        ]
    }

    try:
        for action, expected_output in (("Add", "added"), ("Remove", "removed")):
            result = _run_pwsh(
                FIREWALL,
                "-Action",
                action,
                "-FirewallId",
                TEST_FIREWALL_ID,
                "-RunnerIpv4",
                TEST_RUNNER_IP,
                "-ApiBaseUrl",
                api_base_url,
                env=os.environ | {"DIGITALOCEAN_TOKEN": token},
            )
            assert result.returncode == 0, result.stderr
            assert result.stdout.strip() == (
                f"firewall_ssh_rule={expected_output} cidr={TEST_RUNNER_IP}/32"
            )
            assert token not in result.stdout + result.stderr
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert _FirewallApiHandler.requests == [
        ("POST", expected_rule),
        ("DELETE", expected_rule),
    ]
