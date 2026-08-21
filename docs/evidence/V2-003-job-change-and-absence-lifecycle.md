# V2-003 — JobChange và absence lifecycle

## Kết quả

Canonical Job hiện giữ meaningful change history và lifecycle `active → missing → removed → active` trong cùng PostgreSQL transaction với upsert/finalize. Run không complete không thể tăng absence counter.

## Schema và transaction boundary

Migration `a5e16a7b8c21` thêm:

- `job_changes` với `job_id`, `crawl_run_id`, from/to snapshot provenance, field, old/new JSON value, type và detected time;
- unique `(job_id, crawl_run_id, change_type, field_name)` để một run không sinh event trùng;
- `crawl_runs.items_reactivated` và non-negative constraint.

Change type được khóa ở `created`, `updated`, `missing`, `removed`, `reactivated`. Description change chỉ lưu SHA-256 hai phía trong event; nội dung đầy đủ vẫn truy qua snapshot/Job provenance và không bị copy vào log/event history.

`upsert_parsed_job()` vẫn chỉ flush, không commit. Job, snapshot parse state, run counters và JobChange cùng rollback nếu caller transaction fail. `apply_absence_lifecycle()` chỉ chạy khi final status là `succeeded` và coverage `complete`.

## PostgreSQL acceptance scenario

Fixture source chạy qua runner/persistence thật, không chạm network:

1. complete run đầu tạo hai Job và hai `created` event;
2. complete run tiếp theo cập nhật title Job `501`; Job `502` vắng mặt chuyển `active → missing`, count `1`;
3. một partial run có parse error và một failed discovery run không đổi Job `502` hoặc absence count;
4. complete run tiếp theo vẫn vắng Job `502`: `missing → removed`, count `2`, có `removed_at`;
5. complete run thấy lại Job `502`: reset count/`removed_at`, tạo `reactivated`; title đổi tạo `updated` riêng;
6. observation không đổi sau đó không thêm JobChange.

Tập event của Job `502` được kiểm tra đúng:

```text
created/status
missing/status
removed/status
reactivated/status
updated/title
```

Mỗi event ngoài `created` có from-snapshot evidence; event update/reactivation có to-snapshot evidence và mọi event có `crawl_run_id`.

## Verification

Ngày 2026-08-21 trên Python `3.13.14`, PostgreSQL `18.6`:

```text
python -m pytest                              117 passed
python -m ruff check .                        All checks passed
python -m ruff format --check .               97 files already formatted
python -m mypy                                no issues in 52 source files
python -m pip check                           No broken requirements found
python -m alembic check                       No new upgrade operations detected
```
