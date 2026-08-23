from pathlib import Path


PRODUCTION_COMPOSE = Path("compose.production.yaml")
CADDYFILE = Path("deploy/Caddyfile")
PRODUCTION_ENV = Path(".env.production.example")
WORKFLOW = Path(".github/workflows/deploy-production.yml")
CI = Path(".github/workflows/ci.yml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
