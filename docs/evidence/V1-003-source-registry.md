# V1-003 — Source registry và adapter contract

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** immutable V1 source allow-list, adapter resolution và typed discover/fetch/parse data contract. Không gồm outbound request, safe HTTP/browser fetcher, source parser, fixture capture hoặc database seeding.

## 1. Active registry

Registry active chỉ có ba source đã được operator duyệt cho bounded local non-commercial V1 scope:

| Source key | Adapter key | Discovery | Fetch host |
|---|---|---|---|
| `vng-careers` | `vng_careers` | `server_rendered_html` | `career.vng.com.vn` |
| `naver-vietnam-greenhouse` | `greenhouse_job_board` | `public_json_api` | `boards-api.greenhouse.io` |
| `momo-careers` | `momo_careers` | `browser_public_ui` | `momo.careers` |

Mỗi config khóa base URL, path prefix, content type, throttle/concurrency, timeout, redirect/byte limit, policy review, identity field, pagination strategy và source-specific scope đã có trong approval record. `job-boards.greenhouse.io` chỉ là reference host; `aws.momo.vn` chỉ là browser subresource host, không trở thành top-level fetch host.

GeoComply/Lever không nằm trong active registry vì approval vẫn `candidate` và policy `permission_required`. Test candidate chứng minh adapter tồn tại cũng không thể mở source.

## 2. Fail-closed resolution

- Caller chỉ truyền `source_key`; `SourceRegistry` không nhận URL, host, header hoặc adapter path.
- Source unknown trả stable code `source_not_found`.
- Source khác `approved` trả `source_not_approved` trước outbound work.
- `AdapterRegistry` chỉ trả object đã đăng ký theo exact `adapter_key`; không dynamic import module/class từ chuỗi.
- Adapter thiếu trả `adapter_not_registered`; key dạng `package.module:Adapter` bị config validation reject.
- Duplicate source/adapter key bị reject khi tạo registry.

## 3. Adapter contract

[Typed contract](../../src/devradar/ingestion/contracts.py) giữ ba operation V1:

```text
discover(RunContext) -> Iterable[ListingRef]
fetch(ListingRef, FetchPolicy) -> FetchResult
parse(RawSnapshot) -> ParsedJob | ParseFailure
```

Input/output là frozen dataclass; arbitrary metadata được copy sang read-only mapping. URL bắt buộc HTTPS không user-info, timestamp timezone-aware, fetched payload phải khớp SHA-256, normalized salary/currency giữ invariant và parse failure summary bị giới hạn một dòng 500 ký tự. `ParsedJob` bắt buộc có field evidence và parser version.

Protocol có ba consumer implementation thật đã lên task (`V1-006` đến `V1-008`), nên interface là external-boundary seam đã có nhu cầu, không phải abstraction giả định.

## 4. Verification

| Gate | Kết quả |
|---|---|
| Registry/contract narrow tests | `10 passed` |
| Full suite với PostgreSQL opt-in | `13 passed`, không warning |
| Ruff check/format | Pass |
| mypy strict | Pass, 18 source/test files |
| `pip check` | Pass |
| Internal Markdown links | Pass |

Không thêm dependency hoặc migration. Test không gọi network và không crawl source.

## 5. Boundary còn mở

- Chưa có concrete adapter; adapter source 1–3 thuộc `V1-006`–`V1-008`.
- Chưa có safe fetcher/SSRF/redirect/byte enforcement runtime; thuộc `V1-004`. Registry mới chỉ cung cấp policy đã validate.
- MoMo browser runtime chưa được thêm; chỉ được chọn dependency sau fixture/browser spike trong source task tương ứng.
- Chưa seed `Source` vào PostgreSQL; ingestion bootstrap/upsert sẽ dùng chính registry này ở task persistence workflow, không tạo config thứ hai.
