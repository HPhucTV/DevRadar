# V1 — Phase closeout

**Ngày đóng phase:** 2026-08-21

**Kết quả:** `complete`

## 1. Product decision

Product owner quyết định V1 đo correctness và completeness trong approved scope, không đo quy mô analytics. Fixed gate `>=500 canonical jobs` phụ thuộc inventory bên ngoài và đã thúc đẩy việc mở rộng source ngoài mục tiêu ba-source V1; nó được thay bằng:

> Ingest toàn bộ inventory quan sát được từ tối thiểu ba approved source bằng current adapter version; latest runs phải `succeeded + complete`; Job count phải khớp distinct source/external ID, source/canonical URL và current snapshot count; full replay không tạo duplicate hoặc canonical update giả.

Target `>=500` chuyển sang V3 exit gate, trước khi DevRadar tuyên bố semantic search hoặc trend analytics có quy mô. Không dùng con số 78 làm threshold mới và không diễn giải V1 inventory thành mẫu đại diện thị trường Việt Nam. Đây là product/release decision; không đổi kiến trúc, domain hoặc public API nên không cần ADR mới.

## 2. Exit-criteria mapping

| V1 criterion | Evidence | Kết quả |
|---|---|---|
| Ba approved source, fixture và controlled live run | [NAVER](V1-006-naver-greenhouse-adapter.md), [VNG](V1-007-vng-adapter.md), [MoMo](V1-008-momo-adapter.md) | Pass |
| Full approved inventory và identity 1:1 | [V1-013](V1-013-live-inventory.md): 78 Jobs = 78 source/external IDs = 78 canonical URLs = 78 current snapshots | Pass |
| Current-version complete runs | NAVER `v1` 14, VNG `v2` 27, MoMo `v2` 37; all `succeeded + complete` | Pass |
| Replay/idempotency/rollback | Current-version full replays: `new=0`, `updated=0`, `failed=0`; [upsert evidence](V1-009-job-upsert.md) | Pass |
| Failed/partial không false-remove | Live VNG regression run: `failed + incomplete`, `missing=0`, `removed=0`; PostgreSQL runner tests | Pass |
| REST/OpenAPI contract | [V1-010](V1-010-read-api.md) | Pass |
| Fresh migration, Docker và security negatives | [V1-002](V1-002-postgresql-schema.md), [V1-004](V1-004-safe-fetch-and-snapshot.md), [V1-012](V1-012-compose-and-runner.md) | Pass |
| Provenance và observability | 1:1 current snapshots; [V1-011](V1-011-observability.md) | Pass |
| Source/security boundary | Registry chỉ có ba approved source; GeoComply/Lever vẫn `permission_required`; V1 chỉ bounded local non-commercial | Pass |

## 3. Final verification

```text
Default suite: 103 passed, 7 skipped
PostgreSQL suite: 110 passed
Ruff check: pass
Ruff format: 88 files already formatted
mypy: 48 source files, no issues
pip check: no broken requirements
Compose config: pass
Markdown local links: pass
Git diff whitespace: pass
```

Compose teardown giữ named PostgreSQL volume. V1 hoàn tất; V2 chuyển `in_progress`. Prefect vẫn là candidate cho `V2-001` và chưa được accept chỉ vì phase bắt đầu.
