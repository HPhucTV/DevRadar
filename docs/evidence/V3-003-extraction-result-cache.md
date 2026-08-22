# V3-003 — ExtractionResult, deterministic fallback và accepted-only cache

## Trạng thái

`complete` — 2026-08-22

V3-003 đã có typed payload, deterministic-first orchestration, accepted-only cache, bounded provider
boundary và Alembic migration. Đây là task evidence, không phải V3 phase closeout.

## Scope và non-goals

- PostgreSQL persistence, strict payload validation, deterministic-first orchestration và accepted-only cache.
- Provider callable là test/spike boundary; không có production DeepSeek adapter, SDK, queue, endpoint,
  embedding hoặc backfill.
- Không gửi source JD/CV thật tới provider và không thay đổi source allow-list.

## Verified behavior

- complete deterministic extraction performs zero provider calls;
- accepted cache hit performs zero provider calls;
- cache identity gồm `input_type`, `input_ref`, `input_hash`, extractor/schema/prompt/model/
  canonicalization versions;
- rejected và needs-review attempts có thể audit nhưng không thỏa cache lookup;
- transient failure bounded ở hai attempts; malformed/extra-field/evidence-invalid output bị reject an toàn;
- deterministic `levels`, `experience`, `salary`, `location` không bị provider candidate ghi đè;
- persistence có partial unique index cho accepted và savepoint re-read khi duplicate insert;
- rollback không để lại extraction result nửa chừng;
- safe errors chỉ gồm bounded `code/path/type`, không chứa raw JD/CV/prompt/output/secret.

## Evidence đã chạy

| Gate | Kết quả hiện tại |
|---|---|
| `pytest tests/integration/test_extraction_result.py tests/integration/test_postgresql_schema.py -m postgresql -q` | `8 passed` trên PostgreSQL 18.4 UTF8 disposable cluster |
| `pytest` với `DEVRADAR_TEST_DATABASE_URL` | `155 passed` |
| Alembic `upgrade head` + `alembic check` online | upgrade exit `0`, check exit `0`, revision `b7e3f1c4a902` |
| Alembic offline `upgrade head --sql` | exit `0`, chain tới `b7e3f1c4a902` |
| Ruff check/format | pass trên toàn repository |
| mypy | `Success: no issues found in 64 source files` |
| pip check | `No broken requirements found` |

Integration exercise gồm migration upgrade hai lần, accepted-only index, read-after-write, rejected/
needs-review audit, deterministic zero-provider path, accepted cache hit zero-provider path, rollback
và simulated concurrent duplicate insert re-read. Disposable cluster đã được stop sau verification; không
ghi database URL hoặc credential vào repository.

## Boundaries chưa claim

Không có live provider call, không external JD/CV processing, không semantic embeddings, không public
extraction API và không V3 phase closeout. `TASK_BOARD.md` vẫn là file local-only bị Git ignore.
