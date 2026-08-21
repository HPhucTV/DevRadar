# V1-010 — Read-only REST API evidence

**Ngày kiểm chứng:** 2026-08-21

**Scope:** FastAPI `/api/v1` đọc `Job`, `Source`, `CrawlRun` trên PostgreSQL thật

**Kết quả:** `pass`

## 1. Capability đã triển khai

- `GET /api/v1/jobs` và `GET /api/v1/jobs/{jobId}`;
- `GET /api/v1/sources` và `GET /api/v1/sources/{sourceId}`;
- `GET /api/v1/crawl-runs` và `GET /api/v1/crawl-runs/{runId}`;
- response/query dùng `camelCase`, enum giữ `lower_snake_case`;
- page pagination bounded `1..100`, total count và ordering có `id asc` tie-break;
- Job filter/sort allow-list, salary interval overlap, offset-aware time window;
- error envelope thống nhất cho validation, not-found, database unavailable và unexpected error;
- một synchronous SQLAlchemy `Session` được tạo theo request từ validated PostgreSQL DSN.

Không có mutation endpoint, arbitrary URL input, scheduler, absence lifecycle hoặc capability phase sau trong change này.

## 2. Data exposure boundary

PostgreSQL contract fixture cố ý chứa raw snapshot marker, source policy marker và database error-summary marker. Response assertions chứng minh:

- Job detail chỉ trả plaintext description và current snapshot metadata; không trả `raw_content`, raw hash hoặc HTML payload;
- Source không trả `rate_limit_policy`, `allowed_hosts` hoặc policy secret;
- CrawlRun trả error code cùng public message cố định, không phản chiếu `error_summary`;
- `404`, `422`, `500`, `503` không trả input value, exception hoặc SQL; body/header dùng cùng opaque request ID.

API vẫn mặc định local/private trong V1. Authentication/public exposure không được tuyên bố bởi evidence này.

## 3. Contract đã kiểm chứng

Integration test `tests/integration/test_read_api.py` chạy qua FastAPI vào PostgreSQL mới migrate và kiểm tra:

- stable pagination khi hai Job có cùng `last_seen_at`;
- filter company/title/location/level/source/status/salary/time;
- sort `postedAt asc` với null ở cuối;
- Source/CrawlRun pagination, filtering, detail và safe error;
- detail `404`, unknown query, pagination overflow, invalid salary/time combination;
- exact seven OpenAPI paths gồm health và sáu read resources, path/query parameter camelCase;
- OpenAPI không quảng bá raw snapshot schema.

Negative error tests còn inject `OperationalError` và unexpected exception chứa marker bí mật để xác minh response `503`/`500` đã sanitize và giữ correlation header.

## 4. Commands và kết quả

Targeted contract gate:

```text
$env:DEVRADAR_TEST_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:55432/postgres
python -m pytest tests/integration/test_read_api.py -q
2 passed
```

Default suite không chạm PostgreSQL:

```text
python -m pytest -q
98 passed, 5 skipped
```

Full PostgreSQL gate:

```text
python -m pytest -q
103 passed
```

Static/dependency gates:

```text
python -m ruff check .
All checks passed!

python -m ruff format --check .
78 files already formatted

python -m mypy
Success: no issues found in 42 source files

python -m pip check
No broken requirements found.
```

## 5. Boundary chưa tuyên bố

- Chưa có performance baseline cho count/page query trên dataset 500+; V1-013 sẽ chạy dataset thật.
- Chưa có authentication/authorization; endpoint chỉ dành cho local/private V1.
- Chưa chứng minh browser readiness trong API container; thuộc `V1-012`.
- Health vẫn là process liveness, không phải database readiness.
- V1-010 không tạo CrawlRun hoặc trigger crawler; operator mutation thuộc V2.
