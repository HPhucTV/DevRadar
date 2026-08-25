# One-click Docker Desktop Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép người dùng Windows double-click `start-devradar.cmd` để launcher tự mở/chờ Docker Desktop khi engine chưa ready rồi khởi động toàn bộ DevRadar.

**Architecture:** Giữ root CMD và PowerShell launcher hiện tại. Bổ sung bounded native-process probe, local Docker Desktop context validation, discovery, wait và preflight orchestration; mọi lệnh Docker/Compose pin context `desktop-linux`. Sau preflight, flow Compose/migration/smoke không đổi. Không thêm dependency, service, installer hoặc public configuration.

**Tech Stack:** Windows PowerShell 5.1, Docker Desktop/Docker Compose, Python pytest contract tests, Markdown operations documentation.

---

## File map

- Modify `scripts/start-devradar.ps1`: Docker CLI/engine preflight, Desktop discovery/launch, bounded wait và actionable error.
- Modify `tests/test_deployment_scripts.py`: regression contract cho call order, discovery, process guard, timeout và safety boundary.
- Modify `tests/test_source_recipe_docs.py`: documentation contract cho auto-open/timeout/prerequisite.
- Modify `README.md`: one-click user instructions.
- Modify `docs/OPERATIONS.md`: operator behavior, failure modes và manual fallback.
- Local-only `TASK_BOARD.md`: ghi task/evidence sau verification; file vẫn Git ignored.

Không tạo helper module hoặc dependency mới: launcher hiện tại là một consumer và PowerShell functions nội bộ là seam nhỏ nhất đủ rõ.

## Task 1: Lock Docker Desktop preflight behavior with failing tests

**Files:**

- Modify: `tests/test_deployment_scripts.py:28-74`
- Test: `tests/test_deployment_scripts.py`

- [ ] **Step 1: Add the failing launcher contract tests**

Thêm ngay sau `test_launcher_creates_env_once_and_restores_process_environment`:

```python
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
```

- [ ] **Step 2: Run the two tests and verify RED**

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_deployment_scripts.py::test_launcher_ensures_docker_engine_before_compose tests\test_deployment_scripts.py::test_launcher_discovers_starts_and_boundedly_waits_for_docker_desktop -q
```

Expected: `2 failed`; first failure reports missing `ValidateRange`/`Ensure-DockerEngine`, second reports missing `Find-DockerDesktop`.

Không sửa assertions để khớp code cũ: failure phải chứng minh auto-start behavior chưa tồn tại.

- [ ] **Step 3: Add review-driven safety regressions before the hardened implementation**

Thêm ba RED tests cho: mọi Compose command pin exact local `desktop-linux`; behavioral bounded-process test
terminate child PowerShell bị treo; và `Test-DockerDesktopContext` reject fake remote endpoint. Chạy riêng ba
test và xác minh `3 failed` vì context/functions chưa tồn tại, sau đó mới làm Task 2.

## Task 2: Implement the minimal PowerShell preflight

**Files:**

- Modify: `scripts/start-devradar.ps1:1-67`
- Test: `tests/test_deployment_scripts.py`

- [ ] **Step 1: Add the timeout parameter and bounded local-Docker preflight**

Thay `param()` và chèn các function nội bộ trước `$ErrorActionPreference = "Stop"`:

- khóa `$DockerContext = "desktop-linux"` và exact endpoint
  `npipe:////./pipe/dockerDesktopLinuxEngine`;
- `Invoke-BoundedProcess` dùng `System.Diagnostics.Process`, redirect output, `WaitForExit(timeout)` và
  terminate process khi hết phần deadline;
- `Invoke-DockerCommand` chỉ resolve Docker `Application`, không chạy alias/function tùy ý;
- `Test-DockerDesktopContext` inspect context bằng bounded probe, trả `false` khi context chưa xuất hiện và
  throw khi endpoint khác local named pipe;
- `Test-DockerEngine` gọi bounded `docker --context desktop-linux info`;
- `Find-DockerDesktop`, `Wait-DockerEngine` và `Ensure-DockerEngine` giữ discovery/process guard nhưng dùng
  một absolute UTC deadline cho cả context probe, engine probe và sleep; không có final unbounded probe.

Functions không nhận URL, secret hoặc arbitrary command. `Start-Process` chỉ nhận exact local executable đã
qua `Test-Path -PathType Leaf`. Remote/current Docker context không được chạm build, database hoặc migration.

- [ ] **Step 2: Replace the old Docker preflight and preserve Compose validation**

Trong main `try`, thay:

```powershell
$null = Get-Command docker -ErrorAction Stop
& docker compose version
```

bằng:

```powershell
Ensure-DockerEngine -TimeoutSeconds $DockerReadyTimeoutSeconds
$dockerExecutable = (
    Get-Command docker -CommandType Application -ErrorAction Stop |
        Select-Object -First 1
).Source
Write-Output "Starting DevRadar..."
& $dockerExecutable --context $DockerContext compose version
```

Giữ nguyên check `$LASTEXITCODE`, `.env` create-once, environment restoration, smoke và dashboard open; đổi
mọi Compose invocation còn lại sang exact `$dockerExecutable --context $DockerContext compose ...`.

- [ ] **Step 3: Preserve the actionable exception message**

Thay catch body bằng:

```powershell
catch {
    Write-Error ("DevRadar could not start: {0}" -f $_.Exception.Message)
    $exitCode = 1
}
```

Không in stack trace, environment hoặc `.env` content.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_deployment_scripts.py -q
```

Expected: toàn bộ launcher/deployment tests pass, gồm original preflight tests và ba safety regressions.

- [ ] **Step 5: Parse the actual PowerShell file**

Run:

```powershell
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
    (Resolve-Path 'scripts\start-devradar.ps1'),
    [ref]$tokens,
    [ref]$errors
) | Out-Null
if ($errors.Count -ne 0) { $errors | Format-List; exit 1 }
```

Expected: exit `0`, không có parser error.

- [ ] **Step 6: Commit launcher behavior**

```powershell
git add -- scripts/start-devradar.ps1 tests/test_deployment_scripts.py
git diff --cached --check
git commit -m "feat: auto-start Docker Desktop from launcher"
```

## Task 3: Lock the user-facing documentation contract

**Files:**

- Modify: `tests/test_source_recipe_docs.py:24-31`
- Test: `tests/test_source_recipe_docs.py`

- [ ] **Step 1: Extend the README/operations test before editing docs**

Thay test hiện tại bằng:

```python
def test_readme_documents_one_click_local_recipe_workflow_without_stale_metrics() -> None:
    readme = DOCS["readme"]
    operations = DOCS["operations"]

    assert "start-devradar.cmd" in readme
    assert "http://127.0.0.1:3000/sources" in readme
    assert "Source Recipe" in readme
    assert "tự mở Docker Desktop" in readme
    assert "180 giây" in readme
    assert "không tự cài" in readme
    assert "Docker Desktop" in operations
    assert "180 giây" in operations
    assert "mở thủ công" in operations
    for stale in ("3,339", "1,003", "0.9583"):
        assert stale not in readme
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_docs.py::test_readme_documents_one_click_local_recipe_workflow_without_stale_metrics -q
```

Expected: failure vì README chưa chứa `tự mở Docker Desktop`.

## Task 4: Update Quick Start and operations guidance

**Files:**

- Modify: `README.md:82-94`
- Modify: `docs/OPERATIONS.md:296-304`
- Test: `tests/test_source_recipe_docs.py`

- [ ] **Step 1: Replace the README one-click introduction**

Dùng nội dung:

````markdown
### Chạy một lần nhấp trên Windows

Yêu cầu duy nhất cho product runtime là Docker Desktop đã được cài đặt; không cần mở ứng dụng trước.
Clone repository, sau đó double-click:

```text
start-devradar.cmd
```

Nếu Docker engine chưa sẵn sàng, launcher tự mở Docker Desktop và chờ tối đa 180 giây. Launcher không tự
cài hoặc cập nhật Docker, không vượt màn hình license/login/update; khi timeout, cửa sổ giữ lại thông báo
để bạn mở Docker Desktop thủ công rồi chạy lại.

Sau khi Docker ready, launcher chỉ tạo `.env` từ `.env.example` khi file chưa tồn tại, build ba image,
migrate PostgreSQL, bật API/web/crawler worker trong localhost no-login mode, chạy smoke rồi mở dashboard.
Nó không tự enable hoặc crawl URL và không xóa volume. Workflow nằm tại
`http://127.0.0.1:3000/sources`.
````

Giữ manual development commands bên dưới không đổi.

- [ ] **Step 2: Replace the operations launcher paragraph**

Dùng nội dung:

```markdown
Docker Desktop phải được cài đặt nhưng không cần chạy sẵn. Launcher kiểm tra `docker info`; nếu engine chưa
ready, nó tự mở Docker Desktop từ install location được hỗ trợ, không tạo process trùng và chờ tối đa 180
giây trước khi báo lỗi. Missing CLI/install location hoặc timeout đều trả exit code khác `0`; CMD giữ cửa
sổ mở để operator có thể đọc lỗi, mở Docker Desktop thủ công rồi chạy lại.

Sau preflight, launcher giữ `.env` nếu đã có, build API/web/crawler, migrate, bật localhost no-login +
Source Recipe worker, chạy API/web `/sources`/privacy smoke rồi mới mở dashboard. Nó không tự cài Docker,
auto-enable/auto-crawl recipe hoặc xóa volume. Manual Compose commands trong README/AGENTS là fallback.
```

- [ ] **Step 3: Run docs tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python -m pytest tests\test_source_recipe_docs.py -q
```

Expected: toàn bộ source-recipe documentation contracts pass và local links resolve.

- [ ] **Step 4: Commit documentation behavior**

```powershell
git add -- README.md docs/OPERATIONS.md tests/test_source_recipe_docs.py
git diff --cached --check
git commit -m "docs: explain automatic Docker Desktop startup"
```

## Task 5: Verify the actual one-click ready-engine path twice

**Files:**

- Verify: `start-devradar.cmd`
- Verify: `scripts/start-devradar.ps1`
- Local-only update: `TASK_BOARD.md`

- [ ] **Step 1: Confirm Docker engine and Compose are ready for non-disruptive acceptance**

Run:

```powershell
docker info --format '{{.ServerVersion}}'
docker compose version
```

Expected: cả hai exit `0`. Không stop/kill/restart Docker Desktop vì máy có thể đang chạy container khác.

- [ ] **Step 2: Capture invariants, run the launcher once and compare**

Run:

```powershell
$beforeProcessIds = @(
    Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
) | Sort-Object
$beforeEnvHash = (Get-FileHash -Algorithm SHA256 .env).Hash

cmd.exe /d /c start-devradar.cmd
if ($LASTEXITCODE -ne 0) { throw "First one-click run failed with $LASTEXITCODE" }

$afterProcessIds = @(
    Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty Id
) | Sort-Object
$afterEnvHash = (Get-FileHash -Algorithm SHA256 .env).Hash

if (Compare-Object $beforeProcessIds $afterProcessIds) {
    throw 'Ready-engine path changed Docker Desktop process identity.'
}
if ($beforeEnvHash -ne $afterEnvHash) {
    throw '.env changed during one-click startup.'
}
```

Expected: launcher exits `0`, same Docker Desktop PIDs, same `.env` hash, dashboard opens only after smoke.

- [ ] **Step 3: Verify runtime health and Source Recipe UI**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
docker compose --env-file .env --profile crawler ps
```

Expected: API `status=ok`, web smoke pass, database/API/web/crawler running và required services healthy.

- [ ] **Step 4: Run the launcher a second time**

Run lại Step 2 rồi Step 3.

Expected: second run exit `0`, `.env` hash và Docker Desktop PIDs không đổi; Compose startup idempotent và named volume không bị xóa.

- [ ] **Step 5: Update ignored task board with exact evidence**

Trong `TASK_BOARD.md`, thêm hoặc cập nhật task one-click Docker startup bằng exact test counts, PowerShell parse result, first/second launcher results, API/web smoke và boundary cold-start chưa được thực hiện do không disrupt Docker. Xác minh:

```powershell
git check-ignore -v TASK_BOARD.md
git status --short
```

Expected: `TASK_BOARD.md` bị `.gitignore` match và không xuất hiện trong tracked diff.

## Task 6: Run proportional gates, review, integrate and push

**Files:**

- Verify all changed tracked files.

- [ ] **Step 1: Run focused automated and static gates**

```powershell
.venv\Scripts\python -m pytest tests\test_deployment_scripts.py tests\test_source_recipe_docs.py -q
.venv\Scripts\python -m ruff check tests\test_deployment_scripts.py tests\test_source_recipe_docs.py
.venv\Scripts\python -m ruff format --check tests\test_deployment_scripts.py tests\test_source_recipe_docs.py
docker compose --env-file .env --profile crawler config --quiet
.\scripts\scan-secrets.ps1
```

Expected: tests pass with zero failures; Ruff/config/secret scan exit `0`.

- [ ] **Step 2: Review exact diff and repository state**

```powershell
git diff --check main...HEAD
git diff --stat main...HEAD
git diff main...HEAD -- scripts/start-devradar.ps1 tests/test_deployment_scripts.py tests/test_source_recipe_docs.py README.md docs/OPERATIONS.md
git status --short --branch
```

Expected: only design/plan, launcher, two tests and two documentation files are tracked changes/commits; `.npm-cache/` remains untracked and unstaged.

- [ ] **Step 3: Fast-forward `main` after review**

```powershell
git switch main
git merge --ff-only codex/one-click-docker-desktop
```

Expected: fast-forward, no merge commit.

- [ ] **Step 4: Push with Windows TLS trust store and verify exact SHA**

```powershell
$head = git rev-parse HEAD
git -c http.sslBackend=schannel push origin main
$remote = (git -c http.sslBackend=schannel ls-remote origin refs/heads/main).Split("`t")[0]
if ($remote -ne $head) { throw "Remote main does not match local HEAD." }
```

Expected: push exit `0`; remote SHA equals local HEAD. Không tắt TLS verification.

- [ ] **Step 5: Monitor exact-SHA GitHub Actions to terminal success**

Theo dõi workflow của `$head`, không dùng latest branch run thay exact SHA. Required result là terminal `success` cho đủ seven-check CI chain. Nếu job fail, giữ task mở, lấy exact failing step và sửa theo TDD trước khi push lại.

- [ ] **Step 6: Clean feature branch only after remote success**

```powershell
git branch -d codex/one-click-docker-desktop
git status --short --branch
```

Expected: `main` khớp `origin/main`; chỉ `.npm-cache/` local còn untracked.

## Final requirement trace

- Auto-open Docker Desktop: Tasks 1–2.
- Already-ready fast path/no duplicate process: Tasks 1–2 và Task 5.
- 180-second bounded wait/actionable failure: Tasks 1–4.
- Existing build/migrate/start/smoke behavior preserved: Tasks 2 và 5.
- No admin/service/install/delete/crawl expansion: Tasks 1–4.
- README/operations sync: Tasks 3–4.
- Actual one-click, idempotency, remote proof: Tasks 5–6.
