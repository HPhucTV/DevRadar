# V2-006 — Acceptance cycles và V2 closeout

## Kết quả

V2 hoàn tất direct PostgreSQL-backed automation mà không thêm Prefect, Redis, queue service hoặc dependency mới. Operator API enqueue một `pending` CrawlRun; CLI `work-one` claim tối đa một hàng bằng `FOR UPDATE SKIP LOCKED`, persist `running` trước network work và tiếp tục bounded transient retry qua orchestrator chung.

ROADMAP chuyển V2 sang `complete` và V3 sang `in_progress`. Việc bắt đầu V3 không tự động chấp nhận LLM provider hoặc pgvector; `V3-001` evaluation dataset là task đầu tiên.

## Acceptance evidence

Tất cả scenario dưới đây chạy bằng fixture adapter qua runner, snapshot persistence, Job upsert, JobChange, health policy và PostgreSQL thật; test không mock database và không gọi source live.

| Exit criterion | Evidence | Kết quả |
|---|---|---|
| Nhiều scheduled cycles | Năm slot riêng tạo lần lượt `new`, `updated`, `missing`, `removed`, `reactivated` | Pass |
| Duplicate schedule | Gọi lại slot thứ năm trả cùng run ID, `reused=true`, adapter `0` call, tổng run không tăng | Pass |
| Pending API execution | Cùng API idempotency key trả một pending ID; worker giữ ID đó cho attempt đầu và queue rỗng sau xử lý | Pass |
| Retry policy | Pending attempt fail `network_timeout`, đúng một retry thành công; relation `retryOfRunId` đúng và sleeper bounded | Pass |
| False-removal guard | Existing partial/failed/anomaly tests giữ missing/removal counter bằng `0` | Pass |
| Absence lifecycle | Hai complete run vắng mặt tạo `missing → removed`; complete return tạo `reactivated` | Pass |
| Health/anomaly | Median baseline, inventory-drop downgrade, degraded/recovery metric pass | Pass |
| Quarantine | Policy error quarantine; scheduled/retry block trước adapter; manual complete recovery pass | Pass |
| Run/change API | V2-005 PostgreSQL/OpenAPI tests giữ pagination, provenance, safe error và hidden internal identity | Pass |

Các test acceptance chính là `test_pending_api_run_is_claimed_once_and_retried_outside_http` và `test_v2_scheduled_acceptance_cycles_cover_lifecycle_and_duplicate_trigger`; các lifecycle/health negative scenarios nằm cùng PostgreSQL integration suite.

## Source và runtime boundary

- Không chạy scheduled live crawl trong closeout. VNG, NAVER Vietnam/Greenhouse và MoMo chỉ tiếp tục ở bounded local non-commercial scope hiện hành.
- GeoComply/Lever vẫn `permission_required`; không có adapter/registry route hoặc outbound request nào được thêm.
- `work-one` là process ngắn từ cùng image/codebase, không phải daemon hoặc distributed worker pool. Operator/external local scheduler chịu trách nhiệm gọi command.
- Process crash sau khi claim có thể để run ở `running` để operator điều tra; V2 không tự reset hoặc chạy song song lại. Lease/stale-run recovery chỉ được thêm khi có policy và measured operational need.
- Write API vẫn mặc định disabled và không phải authentication; không bật trên public ingress trước V6.

## Verification

Ngày 2026-08-21 trên Python `3.13.14`, PostgreSQL `18.6`:

```text
python -m pytest                              123 passed
python -m ruff check .                        All checks passed
python -m ruff format --check .               106 files already formatted
python -m mypy                                no issues in 55 source files
python -m pip check                           No broken requirements found
python -m alembic check                       No new upgrade operations detected
docker compose ... config --quiet             exit 0
docker compose ... crawler work-one           {"processed": false}, exit 0
Markdown local-link check                     pass
```

PostgreSQL tests tạo database tên ngẫu nhiên, migrate tới head và drop sau từng case. Default suite không gọi network/LLM.
