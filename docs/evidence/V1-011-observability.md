# V1-011 — Structured observability evidence

**Ngày kiểm chứng:** 2026-08-21

**Scope:** API request/error, Job observation và CrawlRun summary events

**Kết quả:** `pass`

## 1. Implementation

`src/devradar/platform/observability.py` dùng Python standard library để emit JSON line ra stderr. Không thêm dependency, service, metrics endpoint hoặc config tương lai.

Field allow-list được khóa theo bốn event:

- `http_request_completed`: correlation, full route template, method, status, duration;
- `api_error`: correlation, public error code, status và exception class;
- `job_observation_processed`: run/source/snapshot/job IDs, upsert outcome và transaction state;
- `crawl_run_summary`: run/source IDs, status/coverage, duration, counters và safe error code.

String field bị giới hạn một dòng/200 ký tự, float phải finite và unknown event field bị reject. Formatter không serialize free-form log message hoặc exception payload. Logger configuration idempotent và tự re-enable sau khi Alembic `fileConfig()` disable existing logger trong same-process integration test.

## 2. Semantics và privacy boundary

- Request event dùng route template `/api/v1/jobs/{jobId}`; không dùng URL/path value, query, authorization header hoặc body.
- Error event không ghi validation input, exception message, stack trace, SQL hoặc DSN.
- Job event được emit sau `flush` nhưng trước caller commit và ghi rõ `caller_owned_uncommitted`; rollback không bị trình bày sai thành persisted success.
- CrawlRun event không nhận `error_summary`, source URL hoặc raw payload. Runner chỉ được emit summary cuối khi transaction outcome đã rõ.
- Opaque IDs phục vụ trace lookup; metric aggregation không dùng ID làm label.

Persisted counters và source failures vẫn quan sát được qua read-only CrawlRun API. JSON events cung cấp log-derived request/latency/error và domain outcome metrics cho V1; Prometheus/OpenTelemetry chỉ được xem xét khi deployment requirement chứng minh cần.

## 3. Tests

`tests/test_observability.py` xác minh:

- query/header/path markers không xuất hiện trong event;
- full route template thay dynamic path parameter;
- request ID trong response và events khớp nhau;
- domain event chỉ có field allow-list và counter đúng;
- newline payload bị reject;
- logger configuration không tạo duplicate handler.

PostgreSQL Job upsert integration spy xác minh sáu outcome `created/replayed/unchanged/updated/stale/updated` đều emit run correlation và không có title/content field. Full PostgreSQL test order còn tái hiện Alembic logger reset và chứng minh event emitter phục hồi đúng.

## 4. Commands và kết quả

```text
python -m pytest -q
101 passed, 5 skipped

$env:DEVRADAR_TEST_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:55432/postgres
python -m pytest -q
106 passed

python -m ruff check .
All checks passed!

python -m ruff format --check .
80 files already formatted

python -m mypy
Success: no issues found in 44 source files

python -m pip check
No broken requirements found.
```

## 5. Boundary chưa tuyên bố

- Chưa có external collector, dashboard hoặc long-term log retention.
- Chưa có latency/SLO threshold vì chưa có baseline workload.
- `crawl_run_summary` sẽ được run-level CLI/use case gọi trong `V1-012`; V1-011 chỉ khóa safe event contract.
- Event không thay thế PostgreSQL system of record hoặc transaction audit.
