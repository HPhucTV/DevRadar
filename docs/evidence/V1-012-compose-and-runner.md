# V1-012 — Compose và ingestion runner evidence

**Ngày kiểm chứng:** 2026-08-21

**Scope:** on-demand run lifecycle, containerized API/crawler, Chromium sandbox và full V1 quality gate

**Kết quả:** `pass`

## 1. Implementation

`src/devradar/ingestion/runner.py` sở hữu lifecycle manual `CrawlRun` với transaction ngắn: source/run state được commit trước outbound work; mỗi `RawJobSnapshot` được commit trước parse; Job/snapshot/run counter được commit cùng observation. Runner revalidate approved registry config, giữ `missing/removed=0`, sanitize persisted run error và không biến failed/partial/bounded run thành coverage complete.

`src/devradar/cli.py` cung cấp operator command `crawl` với exact V1 source choices, deadline 1–360 phút và optional positive `--max-items`. Không có URL/header/adapter input công khai. `--max-items` tạo bounded run `succeeded + incomplete`; partial/failed trả non-zero.

Docker image pin Playwright `1.62.0`, chỉ cài Chromium headless shell cùng system dependencies. `crawler` là opt-in Compose profile, dùng cùng immutable app image nhưng có entrypoint và sandbox capability riêng; API service không nhận các crawler capability đó. Cả hai service chạy non-root/read-only, drop capabilities và bật `no-new-privileges`; crawler chỉ add `SYS_CHROOT`, official version-matched seccomp profile, `init: true` và host IPC.

Upstream basis:

- Playwright yêu cầu browser binary theo đúng package version và hỗ trợ `install --with-deps --only-shell` cho headless shell: <https://playwright.dev/python/docs/browsers#install-system-dependencies>.
- Với crawling untrusted website, Playwright khuyến nghị separate user + seccomp; `init` và host IPC là Docker recommendations: <https://playwright.dev/python/docs/docker#crawling-and-scraping>.
- `chromium_sandbox` mặc định `false`, nên adapter bật explicit `True`: <https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-option-chromium-sandbox>.
- Seccomp file được pin nguyên bản theo tag dependency: <https://github.com/microsoft/playwright/blob/v1.62.0/utils/docker/seccomp_profile.json>.

## 2. Regression scenarios

PostgreSQL integration kiểm chứng:

- parse failure vẫn giữ raw snapshot ở `invalid` với safe error code;
- successful observation + replay không tạo duplicate hoặc false update;
- failed discovery không đổi Job hiện hữu và không tăng missing/removal;
- bounded `max_items=1` ghi tổng discovery nhưng coverage `incomplete`;
- persisted source config drift bị chặn trước adapter discovery;
- CLI reject source ngoài registry trước database/network và không phản chiếu database exception.

## 3. Container và live smoke

Rebuilt image `devradar-app:local`; API recreate và đạt health. Migration `alembic upgrade head` chạy idempotent trên PostgreSQL Compose.

Chromium smoke trong exact `crawler` profile:

```text
uid=999
browser_version=151.0.7922.34
chromium_processes=7
sandbox_disabled=false
app_writable=false
page_title=DevRadar sandbox smoke
no_new_privs=1
seccomp_mode=2
effective_capabilities=0
capability_bounding_set=0000000000040000 (SYS_CHROOT only)
seccomp_sha256=CC3E61CABDA6BBC1E53E54D27BA4D55A9D3BE829B6DD1A596F4A7B31B1CC7849 (matches upstream v1.62.0)
```

Bounded NAVER command:

```text
crawl --source naver-vietnam-greenhouse --max-items 1 --deadline-minutes 10
status=succeeded
coverage_status=incomplete
items_found=14
items_new=1
items_failed=0
items_missing=0
items_removed=0
```

Sau run, `/api/v1/jobs?pageSize=1` trả một canonical Job `3D Animator - VVX`; `/api/v1/crawl-runs?pageSize=1` trả persisted run/counters tương ứng. Đây là bounded local non-commercial evidence, không phải full inventory.

## 4. Quality gates

```text
python -m pytest
103 passed, 7 skipped

DEVRADAR_TEST_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:55432/postgres
python -m pytest
110 passed

python -m ruff check .
All checks passed!

python -m ruff format --check .
85 files already formatted

python -m mypy
Success: no issues found in 48 source files

python -m pip check
No broken requirements found.

docker compose --env-file .env.example --profile crawler config --quiet
exit 0
```

## 5. Boundary chưa tuyên bố

- Chưa chạy full inventory cả ba source; thuộc `V1-013`.
- Chưa đạt hoặc thay đổi exit gate tối thiểu 500 canonical jobs thật.
- Compose local chưa chứng minh network-level egress firewall, resource/memory limit, production secret isolation hoặc public deployment. Adapter host/IP/route allow-list vẫn là bắt buộc nhưng không được trình bày như lớp network enforcement.
- Host IPC là upstream Chromium recommendation cho local Compose, không phải topology production mặc định.
- V1 chưa có schedule, retry orchestration, absence lifecycle hoặc source health automation; các capability đó thuộc V2.
