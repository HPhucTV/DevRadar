# V1-006 — NAVER Vietnam/Greenhouse adapter

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** deterministic adapter cho approved source `naver-vietnam-greenhouse`, gồm full-list discovery, listing validation, source fetch reuse và list/detail parsing. Không gồm Job persistence/upsert, run counter workflow, scheduler hoặc public API.

## 1. Contract và source boundary

[Adapter implementation](../../src/devradar/ingestion/adapters/greenhouse.py) khóa:

- source key `naver-vietnam-greenhouse`, adapter key `greenhouse_job_board` và board token literal `navervietnam`;
- normal run dùng đúng một public `GET /v1/boards/navervietnam/jobs?content=true`;
- không nhận board token, URL, header hoặc credential từ user/model;
- không gọi detail trong normal run, application POST, question endpoint hoặc Harvest API;
- `id` là external identity; `internal_job_id` chỉ là provenance;
- `absolute_url` phải là exact HTTPS path `/navervietnam/jobs/{id}` trên `job-boards.greenhouse.io`, chỉ dùng làm user-facing canonical reference.

Greenhouse official Job Board docs xác nhận list endpoint trả toàn bộ job posts, public post `id` khác `internal_job_id`, và `content=true` bổ sung full description/department/office: [official Greenhouse API source](https://github.com/grnhse/greenhouse-api-docs/blob/master/source/includes/job-board/_jobs.md).

## 2. Completeness và safe failure

Discovery chỉ trả listing khi:

- root có `jobs` array và `meta.total` integer không âm;
- `len(jobs) == meta.total` và total khác 0;
- mỗi job có unique positive public post ID, bounded title, Vietnam location và valid canonical reference URL;
- optional scalar fields giữ đúng shape.

Empty response, count mismatch, duplicate ID, non-Vietnam location, malformed JSON, URL escape hoặc layout regression tạo stable safe error và không trả partial listing set. Timeout giữ nguyên safe fetch taxonomy. Cache của batch trước bị xóa trước request mới, nên failed discovery không cho fetch listing stale.

## 3. One-request fetch behavior

`content=true` đã chứa full published content. Adapter giữ exact bounded `FetchResult` của discovery hiện tại và trả lại object đó cho từng exact `ListingRef`; không phát sinh detail fan-out. Listing giả, policy khác approved config hoặc listing của batch cũ bị reject.

Thiết kế này giữ raw HTTP response/hash đúng provenance. V1 workflow chạy concurrency 1 và phải hoàn tất batch hiện tại trước discovery kế tiếp. Tối ưu snapshot duplication/reuse chỉ được làm trong transaction workflow khi vẫn giữ traceability; adapter không tự persist hoặc commit.

## 4. Deterministic parsing

Parser hỗ trợ full-list snapshot và optional detail fixture để đối chiếu:

- chọn đúng public post theo snapshot external ID;
- giữ title, canonical URL, location, `internal_job_id`, requisition, language, departments, offices và source `updated_at`;
- chuyển Greenhouse HTML/entity thành plaintext bằng stdlib `HTMLParser`, loại nội dung `script/style/template/noscript` và không trả raw HTML qua canonical field;
- không suy diễn `updated_at` thành `posted_at`;
- normalizer chỉ map location/whitespace theo V1 contract; không LLM, taxonomy hoặc inferred level/experience.

## 5. Fixture evidence

[Fixture set](../../tests/fixtures/greenhouse) đã sanitize và không chứa applicant data/token:

- list happy path có hai Vietnam postings, department/office và missing optional fields;
- detail happy path đối chiếu cùng post;
- HTML entity cùng unsafe script content;
- empty result, `meta.total` mismatch, duplicate ID conflict, malformed JSON và layout regression.

13 adapter tests pass, gồm one-request/no-detail assertion, list/detail parse, nullable fields, safe HTML extraction, timeout/stale-batch, wrong config, candidate source và bounded parse failure.

## 6. Bounded live smoke

Sau khi fixture suite pass, một list request duy nhất chạy qua `SafeHttpFetcher` và adapter thật:

| Thuộc tính | Giá trị |
|---|---:|
| Listings / reported total | `14 / 14` |
| HTTP status | `200` |
| Response bytes | `157,337` |
| SHA-256 | `95495b199034cb78671745c5b6828bfefa78cd42ce1204ee1d002ae1396c35e4` |
| First public post ID | `5733023004` |
| First title/location | `3D Animator - VVX` / `Ho Chi Minh City, Vietnam` |
| First plaintext description length | `6,012` characters |

Không log raw JD. Count/hash/title là observation tại thời điểm smoke, không phải production baseline hoặc quyền tái xuất bản.

## 7. Verification

| Gate | Kết quả |
|---|---|
| Adapter fixture/negative tests | `13 passed` |
| Full suite với PostgreSQL opt-in | `68 passed`, không warning |
| Ruff check/format | Pass |
| mypy strict | Pass, 28 source/test files |
| `pip check` / Alembic drift | Pass / no drift |

## 8. Boundary còn mở

- VNG và MoMo adapters thuộc `V1-007`/`V1-008`.
- Raw snapshot → normalized Job transaction/idempotent upsert thuộc `V1-009`.
- Approval chỉ cho local non-commercial/on-demand V1; public full-JD exposure, commercial reuse, schedule và AI training chưa được duyệt.
