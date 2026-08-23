# V6-012 Production Web Compose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build, deploy, smoke and roll back the Next.js dashboard with FastAPI in the existing Docker Compose topology.

**Architecture:** Next.js 16 standalone output becomes a non-root, read-only web image whose BFF reaches
FastAPI through Compose DNS. Existing PowerShell deploy/rollback commands manage independent API and web
image references as one release surface; CI builds and scans all three API/crawler/web trust boundaries.

**Tech Stack:** Next.js 16.3.2, Node 22, Docker multi-stage build, Docker Compose, PowerShell, pytest,
GitHub Actions, Trivy

---

### Task 1: Define the production web deployment contract

**Files:**

- Create: `tests/test_web_deployment_contract.py`

- [ ] **Step 1: Write the failing contract tests**

```python
from pathlib import Path

WEB_DOCKERFILE = Path("web/Dockerfile")
WEB_DOCKERIGNORE = Path("web/.dockerignore")
NEXT_CONFIG = Path("web/next.config.mjs")
COMPOSE = Path("compose.yaml")
DEPLOY = Path("scripts/deploy.ps1")
ROLLBACK = Path("scripts/rollback.ps1")
WEB_SMOKE = Path("scripts/web-smoke.ps1")
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
    assert "privacy-v1" in smoke
    assert "devradar-web:ci" in ci
    assert "devradar-web:known-good" in ci
    assert "devradar-web:ci" in ci.split("Trivy full reports", maxsplit=1)[1]
```

- [ ] **Step 2: Run RED verification**

```powershell
.venv\Scripts\python -m pytest tests/test_web_deployment_contract.py -q
```

Expected: three failures because web Docker assets/service/release parameters do not exist.

- [ ] **Step 3: Commit RED test**

```powershell
git add tests/test_web_deployment_contract.py
git commit -m "test: define production web deployment contract"
```

### Task 2: Build the standalone web image

**Files:**

- Create: `web/Dockerfile`
- Create: `web/.dockerignore`
- Modify: `web/next.config.mjs`
- Test: `tests/test_web_deployment_contract.py`

- [ ] **Step 1: Enable standalone output and same-origin browser CSP**

Add `output: "standalone"` to `nextConfig` and change `connect-src` to `connect-src 'self'`. Do not add
`NEXT_PUBLIC_*`; `DEVRADAR_API_BASE_URL` remains runtime server-only configuration.

- [ ] **Step 2: Add the pinned multi-stage Dockerfile**

```dockerfile
FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS builder
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim@sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436 AS runner
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000
WORKDIR /app
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
```

- [ ] **Step 3: Add the web build context ignore file**

```text
.env
.env.*
!.env.example
.next
node_modules
npm-debug.log*
tests
```

- [ ] **Step 4: Run targeted checks and build the image**

```powershell
Push-Location web
try { npm run check } finally { Pop-Location }
docker build --pull --tag devradar-web:local web
docker image inspect devradar-web:local --format '{{.Config.User}} {{json .Config.Cmd}}'
```

Expected: web check passes; image user is `node`, command is `["node","server.js"]`.

### Task 3: Add the hardened Compose service and BFF smoke

**Files:**

- Modify: `compose.yaml`
- Modify: `.env.example`
- Create: `scripts/web-smoke.ps1`
- Test: `tests/test_web_deployment_contract.py`

- [ ] **Step 1: Add environment defaults**

Add `DEVRADAR_WEB_IMAGE=devradar-web:local` and `DEVRADAR_WEB_HOST_PORT=3000` to `.env.example`.

- [ ] **Step 2: Add service `web`**

```yaml
  web:
    image: ${DEVRADAR_WEB_IMAGE:-devradar-web:local}
    build:
      context: ./web
    depends_on:
      api:
        condition: service_healthy
    environment:
      DEVRADAR_API_BASE_URL: "http://api:8000"
    ports:
      - "127.0.0.1:${DEVRADAR_WEB_HOST_PORT:-3000}:3000"
    read_only: true
    tmpfs:
      - /tmp
      - /app/.next/cache:uid=1000,gid=1000,mode=0700
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test:
        - CMD
        - node
        - -e
        - >-
          fetch('http://127.0.0.1:3000/login').then((response) => {
            if (!response.ok) process.exit(1)
          }).catch(() => process.exit(1))
      interval: 5s
      timeout: 4s
      retries: 12
      start_period: 5s
```

- [ ] **Step 3: Add `web-smoke.ps1`**

The script accepts `BaseUrl`, `RequireHttps`, and `TimeoutSeconds`; it fails unless `/login` returns `200`
with `DevRadar` in HTML and `/api/devradar/privacy` returns `data.policyVersion=privacy-v1`. It prints only
`web_smoke=pass base_url=<origin>` on success.

- [ ] **Step 4: Run Compose end-to-end smoke**

```powershell
docker compose --env-file .env.example config --quiet
docker compose --env-file .env.example up database --wait
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example up api web --wait
.\scripts\smoke.ps1 -BaseUrl http://127.0.0.1:8000
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
docker compose --env-file .env.example down
```

Expected: database/API/web healthy and both smoke commands pass; named volume remains.

### Task 4: Deploy and roll back both artifacts

**Files:**

- Modify: `scripts/deployment-policy.ps1`
- Modify: `scripts/deploy.ps1`
- Modify: `scripts/rollback.ps1`
- Modify: `README.md`
- Modify: `docs/OPERATIONS.md`
- Test: `tests/test_web_deployment_contract.py`

- [ ] **Step 1: Extend the public policy**

Add `[uri]$WebBaseUrl` to `Assert-DeploymentPolicy`; for `PROTECTED/PUBLIC`, require both API and web URLs
to be HTTPS while retaining auth/managed-secret/CORS/password checks.

- [ ] **Step 2: Extend deploy**

Add defaults `WebImage=devradar-web:local`, `WebBaseUrl=http://127.0.0.1:3000`. Validate both image refs,
build or inspect both, preserve/restore both image environment variables, start `api web --wait`, then run
API and web smoke. Success output includes both image names.

- [ ] **Step 3: Extend rollback**

Add the same web parameters, require both images locally, preserve/restore both image variables, restart
`api web --wait`, and run both smoke commands. Keep schema rollback prohibited.

- [ ] **Step 4: Run dual-image local drill**

```powershell
docker tag devradar-app:local devradar-app:v6-012-known-good
docker tag devradar-web:local devradar-web:v6-012-known-good
.\scripts\deploy.ps1 -EnvironmentFile .env.example -ProjectName devradar -Image devradar-app:local -WebImage devradar-web:local -BaseUrl http://127.0.0.1:8000 -WebBaseUrl http://127.0.0.1:3000 -SkipBuild
.\scripts\rollback.ps1 -EnvironmentFile .env.example -ProjectName devradar -Image devradar-app:v6-012-known-good -WebImage devradar-web:v6-012-known-good -BaseUrl http://127.0.0.1:8000 -WebBaseUrl http://127.0.0.1:3000
docker compose --env-file .env.example down
```

Expected: deploy and rollback report both API/web image refs and both smokes pass.

### Task 5: Enforce web artifact coverage in CI and evidence

**Files:**

- Modify: `.github/workflows/ci.yml`
- Create: `docs/evidence/V6-012-production-web-compose.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Modify local ignored: `TASK_BOARD.md`

- [ ] **Step 1: Update Compose smoke**

Set `DEVRADAR_WEB_IMAGE=devradar-web:ci`, build `web`, start `api web --wait`, and invoke
`scripts/web-smoke.ps1` after API smoke.

- [ ] **Step 2: Update remote rollback**

Build/tag `devradar-web:release` and `devradar-web:known-good`, deploy release API/web, then pass
`-WebImage devradar-web:known-good -WebBaseUrl http://127.0.0.1:3000` to rollback.

- [ ] **Step 3: Update Trivy**

Build `devradar-web:ci` and include it in both full and fixable HIGH/CRITICAL loops. Keep the existing job
name `Container critical/high advisory gate` unchanged.

- [ ] **Step 4: Run full local gates**

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
Push-Location web
try { npm run check } finally { Pop-Location }
git diff --check
```

- [ ] **Step 5: Commit/push and wait for remote proof**

Commit implementation/evidence intent, push `main`, select the exact SHA CI run, and wait for all seven
jobs. Verify Compose artifact contains web service logs and Trivy output includes three images. Record run,
artifact, deploy/rollback and scan results in V6-012 evidence; update task board to `Done` only then.
