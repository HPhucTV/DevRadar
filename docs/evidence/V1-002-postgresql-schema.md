# V1-002 — PostgreSQL schema và migration nền tảng

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** SQLAlchemy mapping, Alembic revision, PostgreSQL constraint/integration test và container migration cho `Source`, `CrawlRun`, `RawJobSnapshot`, `Job`. Không gồm source registry runtime, fetcher, normalization, upsert workflow hoặc domain REST API.

## 1. Stack đã khóa

| Thành phần | Version |
|---|---|
| SQLAlchemy | `2.0.52` |
| Alembic | `1.19.1` |
| Psycopg / binary wheel | `3.3.4` |
| PostgreSQL image/runtime | `postgres:18.6-alpine3.24` / `18.6` |
| Migration head | `ec0ad1a5bfd6` |

Lý do, alternatives và official-source links nằm tại [ADR-005](../decisions/0005-sqlalchemy-alembic-and-psycopg.md).

## 2. Schema và invariants

- `sources`: opaque UUID, approved/health states, non-empty allow-list và policy review evidence bắt buộc trước trạng thái `approved`.
- `crawl_runs`: source provenance, trigger/technical/coverage state tách riêng, non-negative counters và status-time boundary.
- `raw_job_snapshots`: run + source composite provenance, HTTP/hash checks, parse state và deferred raw text.
- `jobs`: current snapshot phải cùng source, source-scoped canonical URL/external ID uniqueness, raw + normalized salary, level allow-list, time/status/hash constraints.

`JobChange` không được tạo trong V1. Schema có lifecycle value `missing/removed` để giữ ubiquitous language, nhưng không có V1 workflow nào được phép chuyển sang các state đó.

## 3. PostgreSQL integration evidence

Test `tests/integration/test_postgresql_schema.py` tạo database tên ngẫu nhiên trên PostgreSQL thật, chạy upgrade head hai lần, chạy `alembic check`, insert graph hợp lệ, rồi xác nhận database reject:

- `approved` source thiếu terms/robots review;
- salary range đảo ngược;
- `Job.current_snapshot_id` trỏ snapshot của source khác;
- external ID trùng trong cùng source.

Test tiếp tục downgrade về base, xác nhận bốn domain table đã mất, upgrade lại và kiểm tra metadata/migration không drift. Kết quả: `1 passed`.

Full test suite với PostgreSQL opt-in: `3 passed`, không warning.

## 4. Static và dependency gates

| Gate | Kết quả |
|---|---|
| Ruff check/format | Pass |
| mypy strict | Pass, 14 source/test files |
| `pip check` | Pass |
| `alembic check` | No new upgrade operations detected |
| hash-locked clean install | Pass |

Runtime lock chỉ thêm SQLAlchemy, Alembic, Psycopg và transitive dependencies; không có Prefect, Redis, pgvector, LLM, LangGraph hoặc browser crawler dependency.

## 5. Docker migration smoke

API image được build lại với runtime lock, `alembic.ini`, migration và source code. Một database mới `devradar_migration_smoke` được tạo, sau đó command sau chạy trong service image dưới user non-root:

```powershell
docker compose --env-file .env.example run --rm `
  -e DEVRADAR_DATABASE_URL=postgresql+psycopg://devradar:devradar_local_only@database:5432/devradar_migration_smoke `
  api python -m alembic upgrade head
```

Database trả revision `ec0ad1a5bfd6` và đủ `sources,crawl_runs,raw_job_snapshots,jobs`. API Compose health vẫn trả HTTP 200 sau build. Database smoke tạm đã được drop; teardown cuối giữ named volume.

## 6. Boundary còn mở

- Process health chưa phải database readiness và API chưa query database.
- Chưa có source registry seed/runtime; thuộc `V1-003`.
- Chưa có safe fetch hoặc payload byte limit; thuộc `V1-004`, nên hiện chưa có production path ghi raw source content.
- Chưa có normalization/upsert transaction; thuộc `V1-005`/`V1-009`.
- PostgreSQL integration test cần `DEVRADAR_TEST_DATABASE_URL` tới server/role được phép tạo database tạm; default unit run không tự chạm PostgreSQL.
