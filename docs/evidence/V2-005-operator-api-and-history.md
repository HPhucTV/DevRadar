# V2-005 — Operator CrawlRun API và JobChange history

## Kết quả

V2 mở hai contract mới dưới `/api/v1`:

- `POST /crawl-runs` enqueue một pending run cho approved registry Source;
- `GET /jobs/{jobId}/changes` trả meaningful history có pagination.

HTTP request không chạy crawler/network inline. Pending run được lưu trong PostgreSQL để worker của `V2-006` claim và xử lý ngoài request lifecycle.

## Trust boundary

- write endpoint mặc định fail-closed khi `DEVRADAR_OPERATOR_WRITE_ENABLED` khác `true`;
- đây là local deployment gate, không phải authentication; không được bật trên public deployment trước V6 auth/authorization review;
- request body hiện chỉ chấp nhận `sourceId`; Pydantic `extra=forbid` chặn URL, adapter path, header hoặc option tùy ý;
- Source phải tồn tại, `approved` và khớp active code registry; candidate/unknown bị chặn trước outbound work;
- `Idempotency-Key` bắt buộc, 8–128 safe ASCII; database chỉ lưu SHA-256, không lưu raw header;
- request hash là canonical JSON của `sourceId`; cùng principal/key/request trả cùng run, khác request trả `409`;
- partial unique active-run constraint làm key mới cho source đang pending/running trả `409`.

Compose truyền write gate với default `false`; `.env.example` không chứa operator secret hoặc tự bật mutation.

## API behavior đã kiểm chứng

| Scenario | Kết quả |
|---|---|
| Write gate tắt | `403 operator_write_disabled`, không tạo run |
| Thiếu/invalid idempotency header | `422 validation_error` |
| Body thêm `url=http://127.0.0.1/...` | `422`, field bị reject |
| Source không tồn tại | `404 source_not_found` |
| Source candidate/unapproved | `403 source_not_approved` |
| Request hợp lệ | `202`, pending CrawlRun, `startedAt=null` |
| Retry cùng key/request | `202`, cùng run ID |
| Cùng key, source khác | `409 idempotency_conflict` |
| Key mới khi source có pending run | `409 source_run_active` |

Response/OpenAPI không chứa trigger key hash, request hash, requester principal, raw idempotency key, rate policy, raw snapshot hoặc secret.

JobChange endpoint trả stable order `detectedAt desc, id asc`, pagination và run/snapshot provenance. Missing Job trả sanitized `404`; fixture history trả `created` rồi `updated/title` mà không lộ raw snapshot.

FastAPI implementation theo official [Header Parameters](https://fastapi.tiangolo.com/tutorial/header-params/), [Request Body](https://fastapi.tiangolo.com/tutorial/body/) và [Response Status Code](https://fastapi.tiangolo.com/tutorial/response-status-code/) patterns cho typed boundary/OpenAPI.

## Verification

Ngày 2026-08-21 trên Python `3.13.14`, PostgreSQL `18.6`:

```text
python -m pytest                              120 passed
python -m ruff check .                        All checks passed
python -m ruff format --check .               104 files already formatted
python -m mypy                                no issues in 54 source files
python -m pip check                           No broken requirements found
python -m alembic check                       No new upgrade operations detected
docker compose ... config --quiet             exit 0
```
