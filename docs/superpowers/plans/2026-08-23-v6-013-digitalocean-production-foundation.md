# V6-013 DigitalOcean Production Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested, fail-closed DigitalOcean production ingress and exact-SHA deployment contract without claiming that a live host or domain already exists.

**Architecture:** Keep the existing Compose modular monolith and add one production override with a pinned Caddy ingress. A manual GitHub `production` environment workflow verifies the exact successful CI SHA, publishes API/crawler/web images to GHCR, temporarily opens SSH only to the runner IPv4, deploys immutable digests, and always removes the firewall rule.

**Tech Stack:** Docker Compose, Caddy 2.10.2, GitHub Actions/GHCR, PowerShell 7, DigitalOcean Firewall REST API, pytest.

---

## File map

- Create `tests/test_production_deployment_contract.py`: static release/Compose assertions plus functional PowerShell boundary tests.
- Create `compose.production.yaml`: Caddy ingress and production restart/hardening overlay only.
- Create `deploy/Caddyfile`: one-host path routing; no secret or arbitrary upstream input.
- Create `.env.production.example`: safe schema with empty secret fields.
- Create `scripts/validate-production-config.ps1`: fail-closed domain/env/image-digest validation reused by CI/deploy.
- Create `scripts/digitalocean-firewall.ps1`: bounded add/remove of one SSH `/32` rule.
- Create `.github/workflows/deploy-production.yml`: exact-SHA publish/deploy workflow.
- Modify `.github/workflows/ci.yml`: validate/smoke production ingress and scan Caddy without changing required job names.
- Modify `docs/OPERATIONS.md`, `docs/runbooks/deploy-rollback.md`, `docs/ROADMAP.md`, local `TASK_BOARD.md`: record command surface and evidence boundary.
- Create `docs/evidence/V6-013-digitalocean-production-foundation.md`: verified local/remote evidence; no live-provider claim.

### Task 1: Establish the production contract in RED

**Files:**
- Create: `tests/test_production_deployment_contract.py`

- [ ] **Step 1: Write static contract tests for ingress, env schema and workflow**

```python
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
    assert "environment:" in workflow and "name: production" in workflow
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
```

- [ ] **Step 2: Run the tests and confirm the missing-contract failure**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py -q
```

Expected: FAIL with `FileNotFoundError` for `compose.production.yaml` or another newly required file.

- [ ] **Step 3: Commit the RED test**

```powershell
git add tests/test_production_deployment_contract.py
git commit -m "test: define production deployment contract"
```

### Task 2: Add the pinned Caddy production overlay

**Files:**
- Create: `compose.production.yaml`
- Create: `deploy/Caddyfile`
- Create: `.env.production.example`
- Test: `tests/test_production_deployment_contract.py`

- [ ] **Step 1: Add the production Compose overlay**

```yaml
services:
  api:
    restart: unless-stopped
  web:
    restart: unless-stopped
  database:
    restart: unless-stopped
  ingress:
    image: caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d
    depends_on:
      api:
        condition: service_healthy
      web:
        condition: service_healthy
    environment:
      DEVRADAR_DOMAIN: ${DEVRADAR_DOMAIN:?DEVRADAR_DOMAIN is required}
    ports:
      - "${DEVRADAR_HTTP_HOST_PORT:-80}:80"
      - "${DEVRADAR_HTTPS_HOST_PORT:-443}:443"
      - "${DEVRADAR_HTTPS_HOST_PORT:-443}:443/udp"
    volumes:
      - ./deploy/Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE
    security_opt:
      - no-new-privileges:true
    restart: unless-stopped

volumes:
  caddy-data:
  caddy-config:
```

- [ ] **Step 2: Add the fixed-route Caddyfile**

```caddyfile
{$DEVRADAR_DOMAIN} {
	log {
		output stdout
		format json
	}

	handle /api/v1/* {
		reverse_proxy api:8000
	}

	handle {
		reverse_proxy web:3000
	}
}
```

- [ ] **Step 3: Add the safe production env schema**

Use literal non-secret configuration and leave both secret fields empty:

```dotenv
DEVRADAR_DOMAIN=devradar.example.com
DEVRADAR_DEPLOYMENT_CLASS=PUBLIC
DEVRADAR_SECRET_SOURCE=managed
DEVRADAR_AUTH_ENABLED=true
DEVRADAR_AUTH_COOKIE_SECURE=true
DEVRADAR_ALLOWED_ORIGINS=https://devradar.example.com
DEVRADAR_OPERATOR_WRITE_ENABLED=true
DEVRADAR_CV_LOCAL_ENABLED=true
DEVRADAR_ALERTS_LOCAL_ENABLED=false
DEVRADAR_OPERATOR_USERNAME=operator
DEVRADAR_OPERATOR_PASSWORD_HASH=
POSTGRES_DB=devradar
POSTGRES_USER=devradar
POSTGRES_PASSWORD=
```

- [ ] **Step 4: Run the ingress/env tests**

Run:

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py -q
```

Expected: ingress/env tests PASS; workflow/CI test remains FAIL because the workflow does not exist.

- [ ] **Step 5: Validate the overlay with sanitized local values**

```powershell
$env:DEVRADAR_DOMAIN='http://localhost'
$env:DEVRADAR_HTTP_HOST_PORT='18080'
$env:DEVRADAR_HTTPS_HOST_PORT='18443'
docker compose --env-file .env.example -f compose.yaml -f compose.production.yaml config --quiet
docker run --rm --env DEVRADAR_DOMAIN=http://localhost --volume "${PWD}/deploy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.10.2-alpine@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d caddy validate --config /etc/caddy/Caddyfile
Remove-Item Env:\DEVRADAR_DOMAIN,Env:\DEVRADAR_HTTP_HOST_PORT,Env:\DEVRADAR_HTTPS_HOST_PORT
```

Expected: both commands exit `0`; Caddy prints `Valid configuration`.

- [ ] **Step 6: Commit the overlay**

```powershell
git add compose.production.yaml deploy/Caddyfile .env.production.example
git commit -m "ops: add pinned production ingress"
```

### Task 3: Enforce production config and bounded firewall mutation

**Files:**
- Create: `scripts/validate-production-config.ps1`
- Create: `scripts/digitalocean-firewall.ps1`
- Modify: `tests/test_production_deployment_contract.py`

- [ ] **Step 1: Add functional negative tests before the scripts exist**

Use `subprocess.run(["pwsh", "-NoProfile", "-File", ...])` against a temporary env file. Assert that a
PUBLIC config with an empty password/hash fails, a complete sanitized config plus three digest image refs
passes, and firewall input `127.0.0.1;whoami` fails before any HTTP request. Add a local
`ThreadingHTTPServer` that records one POST and one DELETE; assert both request bodies contain only:

```json
{"inbound_rules":[{"protocol":"tcp","ports":"22","sources":{"addresses":["203.0.113.7/32"]}}]}
```

Expected API paths are `/v2/firewalls/11111111-1111-4111-8111-111111111111/rules`.

- [ ] **Step 2: Run and verify RED**

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py -q
```

Expected: FAIL because both PowerShell scripts are absent.

- [ ] **Step 3: Implement `validate-production-config.ps1`**

The script must dot-source `deployment-policy.ps1`, require a lowercase DNS hostname matching
`^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$`, call
`Assert-DeploymentPolicy` with `https://$Domain` for both smoke URLs and `-RequireHttps`, require
`DEVRADAR_DEPLOYMENT_CLASS=PUBLIC`, require `DEVRADAR_ALLOWED_ORIGINS=https://$Domain`, reject blank
`POSTGRES_PASSWORD`, and require `DEVRADAR_APP_IMAGE`, `DEVRADAR_CRAWLER_IMAGE`,
`DEVRADAR_WEB_IMAGE` to end in `@sha256:` plus 64 lowercase hex characters. Output only
`production_config=pass domain=<domain>`.

- [ ] **Step 4: Implement `digitalocean-firewall.ps1`**

Parameters are `Action` (`Add`/`Remove`), `FirewallId`, `RunnerIpv4`, and an optional API base URL defaulting
to `https://api.digitalocean.com`. Validate UUID with `Guid.TryParse`, parse IPv4 with
`IPAddress.TryParse` and require `AddressFamily.InterNetwork`, permit an HTTP API base only when host is
loopback, read the bearer token only from `DIGITALOCEAN_TOKEN`, serialize the fixed rule above with
`ConvertTo-Json -Depth 6 -Compress`, then invoke POST for Add or DELETE for Remove. Output only
`firewall_ssh_rule=added|removed cidr=<ip>/32`.

- [ ] **Step 5: Run GREEN and static gates**

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py -q
.venv\Scripts\python -m ruff check tests/test_production_deployment_contract.py
.venv\Scripts\python -m ruff format --check tests/test_production_deployment_contract.py
```

Expected: functional config/firewall tests PASS; workflow test still FAIL.

- [ ] **Step 6: Commit the boundary scripts**

```powershell
git add scripts/validate-production-config.ps1 scripts/digitalocean-firewall.ps1 tests/test_production_deployment_contract.py
git commit -m "ops: enforce production release boundaries"
```

### Task 4: Add exact-SHA GHCR and DigitalOcean deployment workflow

**Files:**
- Create: `.github/workflows/deploy-production.yml`
- Modify: `.github/workflows/ci.yml`
- Test: `tests/test_production_deployment_contract.py`

- [ ] **Step 1: Create the manual production workflow**

The YAML must implement this exact sequence:

1. `workflow_dispatch.inputs.release_sha` required string.
2. Permissions `contents: read`, `actions: read`, `packages: write`; production concurrency with
   `cancel-in-progress: false`.
3. One Ubuntu job with `environment.name: production` and URL from `vars.DEVRADAR_DOMAIN`.
4. Checkout `release_sha` with full history; validate lowercase 40-hex, `git merge-base --is-ancestor` against
   `origin/main`, and query GitHub Actions REST for an exact completed/success `DevRadar CI` run.
5. Build/push `ghcr.io/hphuctv/devradar-{api,crawler,web}:<sha>`, pull each tag, resolve each immutable
   `RepoDigest`, require `@sha256:`, and write a metadata-only release manifest artifact.
6. Decode `secrets.DEVRADAR_PRODUCTION_ENV_B64` to a runner temp file, append the three digest refs and
   `DEVRADAR_DOMAIN`, then call `validate-production-config.ps1`.
7. Write `secrets.DEVRADAR_SSH_PRIVATE_KEY` and `secrets.DEVRADAR_SSH_KNOWN_HOSTS` with mode `0600`.
8. Resolve/validate the runner IPv4, call `digitalocean-firewall.ps1 -Action Add`, copy Compose/Caddy/env to
   `/opt/devradar`, authenticate remote Docker with `GITHUB_TOKEN` over `--password-stdin`, and run remote
   config/pull/database/migration/API/web/ingress commands.
9. Run external HTTPS API, login and privacy BFF smokes.
10. In `if: always()`, remove the exact SSH rule when it was added, remote `docker logout`, delete runner
    temp secrets, and upload only release manifest/smoke metadata.

No secret value may appear in `run-name`, step name, output, artifact or command argument.

- [ ] **Step 2: Extend existing CI without changing seven job names**

In `compose-smoke`, set sanitized Caddy env, validate the two-file Compose model, start `ingress`, then curl:

```bash
curl --fail --silent --show-error http://localhost:18080/api/v1/health
curl --fail --silent --show-error http://localhost:18080/login >/dev/null
curl --fail --silent --show-error http://localhost:18080/api/devradar/privacy | grep -q privacy-v1
```

In `container-advisory`, pull the pinned Caddy image and add it to both full and fixable scan loops under
the local tag `devradar-ingress:ci`.

- [ ] **Step 3: Run contract tests and workflow-sensitive regressions**

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py tests/test_web_deployment_contract.py tests/test_ci_incident_workflow.py -q
```

Expected: all tests PASS.

- [ ] **Step 4: Run a real local ingress route smoke**

Build API/web images, set the sanitized Caddy environment, start/migrate the two-file project, then run the
three HTTP calls from Step 2. Inspect ingress and confirm read-only root, `CapDrop=["ALL"]`,
`CapAdd=["NET_BIND_SERVICE"]`, and Caddy named volumes. Teardown with `docker compose ... down` without
`--volumes`.

- [ ] **Step 5: Commit workflow/CI integration**

```powershell
git add .github/workflows/deploy-production.yml .github/workflows/ci.yml tests/test_production_deployment_contract.py
git commit -m "ci: add exact SHA production release workflow"
```

### Task 5: Document, verify, push and collect remote evidence

**Files:**
- Create: `docs/evidence/V6-013-digitalocean-production-foundation.md`
- Modify: `docs/OPERATIONS.md`
- Modify: `docs/runbooks/deploy-rollback.md`
- Modify: `docs/ROADMAP.md`
- Modify local-only: `TASK_BOARD.md`

- [ ] **Step 1: Document only verified boundaries**

Record exact image pins, local ingress route smoke, validation/firewall negative tests, secret handling,
release workflow contract and remaining provider inputs. Mark V6-013 `In Progress` until remote CI on the
implementation SHA succeeds; keep V6-004/V6-005/V6-007 `In Progress` and explicitly state that no public
host/TLS/Spaces/Uptime evidence exists yet.

- [ ] **Step 2: Run full verification**

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m ruff format --check .
.venv\Scripts\python -m mypy
.venv\Scripts\python -m pip check
.\scripts\scan-secrets.ps1
docker compose --env-file .env.example --profile crawler config --quiet
git diff --check
```

Expected: all commands exit `0`; test output has zero failures.

- [ ] **Step 3: Review and commit docs**

```powershell
git diff --check
git status --short --branch
git add docs/OPERATIONS.md docs/runbooks/deploy-rollback.md docs/ROADMAP.md docs/evidence/V6-013-digitalocean-production-foundation.md
git commit -m "docs: record production foundation boundary"
```

Do not stage `TASK_BOARD.md`.

- [ ] **Step 4: Push and verify exact-SHA CI**

```powershell
git push origin main
```

Wait for the exact pushed SHA. Require all seven named jobs terminal `success`; verify the incident workflow
success path is skipped and creates no issue.

- [ ] **Step 5: Close V6-013 evidence without evidence-loop commits**

Update V6-013 evidence/roadmap once with the first remote run ID and artifact digests, commit and push. Wait
for the final evidence SHA's seven checks, but do not create another commit solely to record that final run.
V6-014 begins only after this final run is terminal success.
