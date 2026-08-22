# V3-004 — Taxonomy, classification và bounded summary

**Ngày kiểm chứng:** 2026-08-22  
**Phase:** V3 (`in_progress`)

## Scope và non-goals

V3-004 thêm typed deterministic boundary cho `job-taxonomy-v1`, role classification và bounded summary. Implementation dùng lại alias/evidence extraction của V3-003, giữ `Job.levels` làm scalar source of truth và fail closed khi skill chưa map, role mơ hồ hoặc summary có claim ngoài evidence.

Task không thêm table/migration, public endpoint, provider SDK/model call, DeepSeek production adapter, queue, pgvector, semantic search hoặc backfill. Không gửi JD/CV thật ra external provider.

## Verified behavior

- known skill map vào category versioned và giữ requirement type/evidence;
- unknown skill giữ name/evidence với `category=other` nhưng trả `needs_review`;
- role marker trong title có precedence; tie hoặc thiếu marker không auto-classify;
- role classification không override canonical levels;
- bounded summary là một dòng tối đa 420 ký tự, tối đa 8 evidence claims;
- summary text phải khớp renderer deterministic từ role/skill evidence, nên extra prose, salary, benefit hoặc unsupported skill claim bị reject;
- malformed/extra-field/control-character/evidence-invalid candidate bị reject bằng safe error code;
- prompt-injection-like JD text chỉ là data và không đi vào summary/tool/action;
- baseline extraction hiện có không regression.

## TDD và commands

Test đỏ ban đầu:

```text
.venv\Scripts\python -m pytest tests/test_taxonomy.py -q
ERROR: ModuleNotFoundError: No module named 'devradar.intelligence.taxonomy'
```

Negative test bổ sung cho arbitrary unsupported prose cũng được quan sát fail trước khi renderer exact được triển khai.

Final narrow gate:

```text
.venv\Scripts\python -m pytest tests/test_taxonomy.py tests/test_extraction.py tests/test_ai_evaluation.py -q
23 passed
```

Full/default và static gates:

```text
.venv\Scripts\python -m pytest
145 passed, 22 skipped

.venv\Scripts\python -m ruff check .
All checks passed!

.venv\Scripts\python -m ruff format --check .
128 files already formatted

.venv\Scripts\python -m mypy
Success: no issues found in 66 source files

.venv\Scripts\python -m pip check
No broken requirements found.

git diff --check
exit 0; chỉ có line-ending warning của Git trên working copy
```

22 test PostgreSQL opt-in bị skip vì `DEVRADAR_TEST_DATABASE_URL` không được set. Docker Desktop engine không chạy (`dockerDesktopLinuxEngine` named pipe không tồn tại), nên task không giả nhận Alembic/PostgreSQL integration mới. V3-004 không thay model/migration/database query; verified PostgreSQL proof của V3-003 vẫn nằm tại [V3-003 evidence](V3-003-extraction-result-cache.md).

## Boundaries chưa claim

- Chưa có aggregate role-classification accuracy/summary hallucination target trên held-out dataset mở rộng; V3-006 phải đo trước production provider use.
- Chưa persist taxonomy/classification/summary và chưa public chúng qua API.
- Chưa có embedding, semantic query, trend API hoặc V3 phase closeout.
