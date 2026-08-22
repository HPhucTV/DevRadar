# V3-003 — ExtractionResult, deterministic fallback và accepted-only cache

## Trạng thái

`implementation complete; PostgreSQL integration gate pending local database access`

V3-003 đã có typed payload, deterministic-first orchestration, accepted-only cache, bounded provider
boundary và Alembic migration. Không nâng phase V3 và không tuyên bố PostgreSQL integration pass khi
database opt-in chưa chạy được trên máy hiện tại.

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
| `pytest tests/test_ai_evaluation.py tests/test_extraction.py -q` | `11 passed` |
| `pytest tests/integration/test_extraction_result.py -m postgresql -q` | `7 skipped` — không có `DEVRADAR_TEST_DATABASE_URL`; Docker daemon không chạy và local PostgreSQL không có credential test |
| Alembic offline `upgrade head --sql` | exit `0`, chain tới `b7e3f1c4a902` |
| Ruff check/format | pass trên các file V3-003 |
| mypy | pass trên các file V3-003 |

Integration PostgreSQL, `alembic check` online, concurrent writer thật và full repository gate phải
được chạy lại sau khi có database tạm đúng command trong `AGENTS.md`. Kết quả skipped không được
diễn giải thành integration pass.

## Boundaries chưa claim

Không có live provider call, không external JD/CV processing, không semantic embeddings, không public
extraction API và không V3 phase closeout. `TASK_BOARD.md` vẫn là file local-only bị Git ignore.
