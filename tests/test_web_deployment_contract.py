from pathlib import Path

WEB_DOCKERFILE = Path("web/Dockerfile")
WEB_DOCKERIGNORE = Path("web/.dockerignore")
NEXT_CONFIG = Path("web/next.config.mjs")
COMPOSE = Path("compose.yaml")
LOCAL_ENV = Path(".env.example")
PRODUCTION_ENV = Path(".env.production.example")
DEPLOY = Path("scripts/deploy.ps1")
ROLLBACK = Path("scripts/rollback.ps1")
WEB_SMOKE = Path("scripts/web-smoke.ps1")
SUPPLY_CHAIN = Path("scripts/scan-supply-chain.ps1")
CI = Path(".github/workflows/ci.yml")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_web_image_is_standalone_pinned_and_non_root() -> None:
    dockerfile = _read(WEB_DOCKERFILE)
    config = _read(NEXT_CONFIG)
    dockerignore = _read(WEB_DOCKERIGNORE)

    assert 'output: "standalone"' in config
    assert "node:22-bookworm-slim@sha256:d649c27d" in dockerfile
    assert "npm ci --no-audit --no-fund" in dockerfile
    assert "npm run build" in dockerfile
    assert "/app/.next/standalone" in dockerfile
    assert "/app/.next/static" in dockerfile
    assert "rm -rf /usr/local/lib/node_modules/npm" in dockerfile
    assert "/usr/local/bin/npm" in dockerfile
    assert "USER node" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "node_modules" in dockerignore
    assert ".next" in dockerignore
    assert ".env.*" in dockerignore


def test_compose_web_is_loopback_internal_api_and_hardened() -> None:
    compose = _read(COMPOSE)

    assert "DEVRADAR_WEB_IMAGE" in compose
    assert "DEVRADAR_WEB_HOST_PORT" in compose
    assert 'DEVRADAR_API_BASE_URL: "http://api:8000"' in compose
    assert "127.0.0.1:${DEVRADAR_WEB_HOST_PORT:-3000}:3000" in compose
    assert "condition: service_healthy" in compose
    assert "/app/.next/cache" in compose
    assert "read_only: true" in compose
    assert "no-new-privileges:true" in compose


def test_local_no_login_is_explicit_and_defaults_off() -> None:
    compose = _read(COMPOSE)
    local_env = _read(LOCAL_ENV)
    production_env = _read(PRODUCTION_ENV)

    assert compose.count("DEVRADAR_LOCAL_NO_LOGIN_ENABLED") >= 2
    assert "DEVRADAR_LOCAL_NO_LOGIN_ENABLED=false" in local_env
    assert "DEVRADAR_LOCAL_NO_LOGIN_ENABLED=false" in production_env


def test_release_commands_and_ci_cover_web_and_api() -> None:
    deploy = _read(DEPLOY)
    rollback = _read(ROLLBACK)
    smoke = _read(WEB_SMOKE)
    ci = _read(CI)

    for script in (deploy, rollback):
        assert "WebImage" in script
        assert "WebBaseUrl" in script
        assert "DEVRADAR_WEB_IMAGE" in script
        assert "web-smoke.ps1" in script
    assert "/login" in smoke
    assert "/api/devradar/privacy" in smoke
    assert "privacy-v3" in smoke
    assert "devradar-web:ci" in ci
    assert "devradar-web:known-good" in ci
    assert "devradar-web:ci" in ci.split("Trivy full reports", maxsplit=1)[1]


def test_local_supply_chain_scan_covers_api_crawler_and_web_images() -> None:
    scan = _read(SUPPLY_CHAIN)

    assert '$WebImage = "devradar-web:local"' in scan
    assert "$images = @($Image, $CrawlerImage, $WebImage)" in scan
