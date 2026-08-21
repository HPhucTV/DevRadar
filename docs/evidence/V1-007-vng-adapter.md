# V1-007 — VNG Careers adapter

**Ngày kiểm tra:** 2026-08-21

**Kết quả:** `pass`

**Scope:** HTTP-first adapter cho approved source `vng-careers`, gồm public job-group discovery, pagination completeness, detail fetch, deterministic parse và contact redaction. Không gồm Job upsert, run counters, scheduler hoặc public API.

## 1. Source-shaped scope decision

Bounded capture xác nhận VNG vẫn server-render `__NEXT_DATA__`, `job_id`, total/pages và public filter taxonomy tại [VNG job list](https://career.vng.com.vn/tim-kiem-viec-lam). Live job card hiện trả broad `job_family` như `Tech`, `Data`, `Product`, `Business Operations` hoặc `null`; field này không còn map trực tiếp tới approved IT families.

Adapter không suy đoán scope từ title hoặc broad family. [Registry](../../src/devradar/ingestion/source_registry.py) version `2026-08-21.2` pin tám cặp public UI `job_group` ID/name:

| ID | Approved group |
|---:|---|
| `385` | Software |
| `423` | System |
| `384` | QC/P-QA |
| `387` | Tech Management |
| `457` | Data Engineering |
| `462` | Data Science |
| `464` | Business Analysis |
| `465` | Artificial Intelligence |

Mỗi request dùng `/tim-kiem-viec-lam?job_group=<id>&page=<n>`. Parser chỉ chấp nhận page tự xác nhận exact ID ở `request.queries.job_group` và exact ID/name mapping trong public `tags`; mismatch fail closed với `scope_filter_mismatch`.

## 2. Pagination và identity

[Adapter implementation](../../src/devradar/ingestion/adapters/vng.py):

- validate one complete `__NEXT_DATA__` JSON payload, requested page, positive size/pages, non-negative total và exact item count;
- đi đủ page cho từng approved group, giữ total/pages/size ổn định;
- dùng positive `job_id` làm source-scoped identity; slug chỉ tạo canonical detail URL;
- chấp nhận consecutive hyphen trong source slug nhưng chỉ lowercase ASCII alphanumeric/hyphen, exact `job_id-` prefix, no query/fragment/host escape;
- duplicate trong một group bị reject; cùng job ở nhiều approved groups chỉ merge khi URL/title không conflict;
- failed/malformed/page-timeout attempt xóa discovery cache trước, nên listing batch cũ không thể fetch.

## 3. Deterministic detail parsing

Detail GET chỉ chạy cho exact listing sau complete discovery. Parser:

- đối chiếu snapshot `job_id` và approved detail URL;
- reject detail `closed` hoặc identity mismatch;
- giữ title, location, code, language, department/category, working type, status và raw evidence;
- chuyển description/requirement/excerpt HTML thành plaintext, loại `script/style/template/noscript`;
- redact email và explicit Vietnam phone pattern khỏi canonical description, thêm warning `contact_data_redacted`;
- giữ `post_on_careers_page` như source flag integer; không diễn giải thành date/posted timestamp;
- không suy diễn salary, level hoặc experience khi source không cung cấp field explicit.

## 4. Fixture và negative evidence

[Fixture set](../../tests/fixtures/vng) gồm page 1/page cuối, multi-group duplicate, detail happy/closed, optional/null broad family, contact data, consecutive-hyphen slug, empty total, missing/malformed `__NEXT_DATA__`, cross-page duplicate, pagination conflict và slug change.

13 VNG tests pass, gồm multi-page/group completeness, exact public query, cross-group dedup, detail fetch, HTML/contact safety, timeout stale-batch, identity/closed/config/candidate negative paths. Greenhouse adapter regression vẫn pass sau khi HTML plaintext helper được chia sẻ.

## 5. Bounded live smoke

Smoke dùng một `SafeHttpFetcher`, nên ba request tuân thủ throttle 6 request/phút: Software page 1, page 2 và một detail từ listing đã validate.

| Observation | Giá trị |
|---|---|
| Approved filter | `385:Software` |
| Page coverage | `10 + 1 = 11`, `total=11`, `pages=2`, stable |
| Page 1 | `200`, `143,993` bytes, SHA-256 `0c5b834e752771987fbe95d16081142a81744eea8255c661ca6630c9e7a0db48` |
| Page 2 | `200`, `51,754` bytes, SHA-256 `7d067145a4e425b429f18f231ca68f617d8717f19e5fc2d0422910191592900d` |
| Detail | `200`, `60,997` bytes, SHA-256 `8a69a7f0bed9c6acd191a5ea7d6912adcd67542b13186248c4815a31c70e7f43` |
| Parsed identity | `6849` — `Senior Software Engineer (AI Inference), GreenNode` |
| Location/plaintext | `Thành phố Hồ Chí Minh`, `2,764` characters |

Smoke không log raw JD, không gọi API nền/browser/form và không chạy toàn source. Counts/hash/title là observation tại thời điểm kiểm tra, không phải baseline production hoặc license tái xuất bản.

## 6. Verification

| Gate | Kết quả |
|---|---|
| VNG fixture/negative tests | `13 passed` |
| Full suite với PostgreSQL opt-in | `81 passed`, không warning |
| Ruff check/format | Pass |
| mypy strict | Pass, 31 source/test files |
| `pip check` / Alembic drift | Pass / no drift |

## 7. Boundary còn mở

- MoMo browser adapter thuộc `V1-008`.
- Raw snapshot → normalized Job transaction/idempotent upsert thuộc `V1-009`.
- Full on-demand run phải crawl đủ tám groups before `coverage_status=complete`; smoke chỉ chứng minh one-group path.
- Approval chỉ cho local non-commercial/on-demand V1; public full-JD exposure, schedule, commercial reuse và AI training chưa được duyệt.
