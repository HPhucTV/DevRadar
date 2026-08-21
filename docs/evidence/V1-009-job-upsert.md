# V1-009 — Idempotent Job upsert và source-scoped dedup

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** chuyển một `ParsedJob` + `RawJobSnapshot` đã persist thành current-state `Job` trong transaction caller, gồm identity resolution, canonical hash, run counters, replay/stale protection và rollback. Không gồm crawl-run orchestration/finalization, `JobChange`, absence lifecycle, public API hoặc concurrent worker topology.

## 1. Transaction ownership

[Implementation](../../src/devradar/catalog/job_upsert.py) nhận `Session`, persisted `CrawlRun`, `RawJobSnapshot`, `ParsedJob` và exact approved `SourceConfig`. Function:

- lock run, snapshot, source và existing Job rows;
- chỉ chấp nhận run `running`, snapshot `pending` và provenance/config khớp source đã persist;
- dùng SQLAlchemy unit of work rồi gọi `Session.flush()`; không `commit()` hoặc `rollback()`;
- cập nhật Job, snapshot `parse_status` và `CrawlRun.items_new/items_updated` trong cùng database transaction.

Thiết kế theo SQLAlchemy 2.0 session contract: flush phát DML trong transaction hiện tại nhưng transaction vẫn do caller kết thúc; rollback trả pending insert/update về state đã commit. Xem [official Session flush/rollback docs](https://docs.sqlalchemy.org/en/20/orm/session_basics.html#flushing) và [Session API](https://docs.sqlalchemy.org/en/20/orm/session_api.html#sqlalchemy.orm.Session.flush).

Không thêm generic repository, Unit-of-Work wrapper hoặc async stack. Module `catalog` sở hữu canonical Job/dedup; application workflow tương lai chỉ sở hữu transaction/run boundary.

## 2. Identity và canonical validation

Lookup dùng `SELECT ... FOR UPDATE` theo thứ tự:

1. `(source_id, external_id)`;
2. `(source_id, normalized canonical_url)`.

Nếu hai key trỏ hai Job khác nhau, hoặc canonical URL đã thuộc external ID khác trong cùng source, operation fail closed với `identity_conflict`; không merge. Cùng external ID ở hai source tạo hai Job khác nhau. Slug/canonical URL đổi nhưng external ID giữ nguyên cập nhật cùng Job.

Trước persistence, service:

- normalize canonical URL chỉ trên approved fetch/reference hosts;
- đối chiếu raw title/company/description với normalized candidates;
- validate work mode, salary period, ordered level enum, experience range và field length;
- dựng exact `CanonicalJobContent` rồi hash bằng schema `job-content-v1` đã khóa ở V1-005.

DB unique constraints vẫn là lớp cuối. Initial-insert concurrency hiện dựa trên approved source concurrency `1`; nếu V6 đo được nhu cầu multi-worker, phải thêm conflict retry/`ON CONFLICT` strategy và test concurrent transaction, không chỉ bỏ giới hạn.

## 3. Outcome và counter semantics

| Outcome | Current Job | Snapshot | Run counter |
|---|---|---|---|
| `created` | tạo active Job, first/last seen bằng observation | `parsed` | `items_new + 1` |
| `updated` | cập nhật canonical fields/hash/current snapshot/last seen | `parsed` | `items_updated + 1` |
| `unchanged` | giữ content, cập nhật current snapshot/last seen | `parsed` | không tăng new/updated |
| `stale` | không ghi đè state mới hơn | `parsed` | không tăng |
| `replayed` | cùng processed snapshot/equal-time same content không đổi | giữ `parsed` | không tăng |

Equal-time observation khác canonical hash bị reject vì không có deterministic ordering. Existing Job ở `missing/removed` hoặc missing counter khác `0` bị reject `unsupported_job_state`; V1 không tự kích hoạt reactivation/absence semantics của V2. Không tạo `JobChange` trong bất kỳ path nào.

## 4. PostgreSQL integration evidence

[Integration tests](../../tests/integration/test_job_upsert.py) chạy trên fresh PostgreSQL database đã Alembic upgrade:

- create → same-snapshot replay → new unchanged snapshot → meaningful title update;
- stale older snapshot không rollback title/current snapshot/counter;
- canonical slug change giữ Job ID và đổi current URL/hash;
- cùng external ID ở VNG và MoMo vẫn tạo hai source-scoped Jobs;
- canonical URL/external ID conflict fail closed;
- caller rollback sau create xóa Job và phục hồi run counter/snapshot `pending`;
- caller rollback sau update phục hồi title/current snapshot, `items_updated=0` và snapshot `pending`.

Tests query database sau rollback, không chỉ assert ORM object trước rollback.

## 5. Verification

| Gate | Kết quả |
|---|---|
| V1-009 PostgreSQL scenarios | `2 passed` |
| Full suite với PostgreSQL opt-in | `99 passed`, không warning |
| Ruff check/format | Pass, `69` files |
| mypy strict | Pass, `35` source/test files |
| `pip check` / Alembic drift | Pass / no drift |
| Migration | Không cần schema change; dùng V1 constraints hiện có |
| Teardown | Database/network removed; named volume preserved |

## 6. Boundary còn mở

- `V1-010` cung cấp read-only `/api/v1/jobs`, `/sources`, `/crawl-runs`; raw snapshots/content không public.
- Run-level adapter → fetch → snapshot → parse → upsert orchestration/finalization và production-like crawler command còn thuộc V1 quality/integration tasks; function này không tự đổi run status/coverage.
- `JobChange`, missing/removed/reactivated và absence counters chỉ bắt đầu V2 sau complete-run gates.
