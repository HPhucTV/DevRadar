# V3-004 Taxonomy, classification và bounded summary — Implementation Plan

> Thực thi inline theo spec đã duyệt; giữ giải pháp lean và không delegate.

**Goal:** Cài typed, deterministic taxonomy/classification/bounded-summary boundary cho Job intelligence mà không thêm persistence, endpoint, provider SDK hay dependency phase sau.

**Architecture:** Reuse alias/evidence extraction từ `intelligence.evaluation`; `intelligence.taxonomy` map category và role marker theo version. Classification và summary trả outcome typed với safe errors. Summary builder chỉ nhận accepted evidence; candidate validator fail-closed.

## File map

| File | Trách nhiệm |
|---|---|
| `src/devradar/intelligence/evaluation.py` | Mở rộng requirement enum/marker mà không đổi alias vocabulary hoặc held-out semantics. |
| `src/devradar/intelligence/taxonomy.py` | Taxonomy models, category map, role classifier, summary builder và candidate validation. |
| `tests/test_taxonomy.py` | TDD contract cho taxonomy/classification/summary và negative cases. |
| `docs/DOMAIN_MODEL.md` | Skill taxonomy, role classification và summary semantics. |
| `docs/AI.md` | Version/evidence/status/validation boundary. |
| `docs/OPERATIONS.md` | Test/telemetry/failure boundary, không raw JD/CV. |
| `docs/evidence/V3-004-taxonomy-classification-summary.md` | Commands và evidence thực tế. |
| `TASK_BOARD.md` | Local-only status; không stage/commit. |

## Task 1 — RED tests

- Viết test cho category map known/unknown, preferred/optional preservation, role unique/tie/no marker, levels precedence, evidence validation, bounded summary và prompt-injection-like source.
- Chạy `pytest tests/test_taxonomy.py -q` và xác nhận fail vì module/contract chưa có.

## Task 2 — GREEN implementation

- Thêm enum/model typed với Pydantic strict extra-forbid, version fields và bounds.
- Reuse `canonicalize_skill_name`/`extract_skill_expectations`; thêm category map canonical-only.
- Implement role marker scorer deterministic, ambiguity => `needs_review`.
- Implement summary builder từ accepted claims và candidate validator với evidence/allow-list/size checks.
- Chạy narrow unit test, Ruff, format và mypy; refactor chỉ sau green.

## Task 3 — Docs/evidence/board

- Cập nhật DOMAIN_MODEL/AI/OPERATIONS, không thêm API/migration.
- Ghi evidence chỉ bằng output command thực tế, không chứa source JD/CV/secret.
- Chuyển `V3-004` sang `Done`, `V3-005` sang `Ready` trong board local-only; giữ ROADMAP V3 `in_progress`.

## Task 4 — Final verification

- Chạy test taxonomy, full suite, Ruff, format, mypy, pip check, Alembic check và `git diff --check`.
- Kiểm tra không có dependency/lockfile/API/provider/persistence mới; `TASK_BOARD.md` bị ignore.
- Commit V3-004; chưa push vì V3-005/V3-006 còn mở.
