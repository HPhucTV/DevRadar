# Local Document Import and Safe Browser Routing Design

## 1. Mục tiêu

Cho phép operator local thu thập job từ một trang họ mở được bình thường bằng cách lưu trang thành
HTML, JSON hoặc CSV rồi import vào `SourceRecipe` tương ứng. Import phải tái sử dụng normalization,
source-scoped identity, idempotent upsert, `CrawlRun`, `RawJobSnapshot` và `JobChange` hiện có nhưng
không tạo một URL fetch proxy, không dùng session/cookie của browser và không thay đổi no-bypass
boundary trong ADR-026.

Slice này đồng thời sửa false `route_policy_blocked`: browser preview được phép bỏ qua subresource
CDN/analytics ngoài allow-list mà không làm hỏng toàn bộ preview, trong khi navigation, redirect, SSRF
và access-control signal vẫn fail-closed.

## 2. Phạm vi

### Có trong slice đầu tiên

- sửa phân loại browser route giữa document navigation và subresource;
- import file `.html`/`.htm`, `.json` và `.csv` qua dashboard local;
- deterministic parse, seniority filter, provenance, idempotency và canonical persistence;
- API/OpenAPI, BFF, UI Việt/Anh, negative tests và documentation contract;
- imported run luôn có coverage `incomplete` và không tham gia absence/removal signal.

### Không có trong slice đầu tiên

- browser extension/bookmarklet hoặc đọc DOM/cookie/session từ browser đang mở;
- official API/feed connector cho TopCV, Vieclam24h hoặc ATS khác;
- URL/header/cookie/proxy/credential override theo import;
- tự động vượt CAPTCHA, login, paywall, `401/403` hoặc anti-bot;
- tự chạy pagination, tải detail URL hoặc schedule lại file import;
- chạy script, stylesheet, iframe hoặc network request từ HTML đã upload;
- LLM selector/mapping và retention file upload gốc.

Extension và official connector là hai subsystem độc lập; chỉ brainstorm/spec riêng sau khi slice này có
evidence vận hành.

## 3. Các hướng đã cân nhắc

### A. Import bounded trực tiếp vào recipe hiện có — chọn

Một multipart endpoint nhận file nhỏ, parse và ingest đồng bộ. Không có outbound network và không lưu
file gốc sau request. Cách này nhỏ nhất, giải quyết ngay trường hợp browser người dùng xem được nhưng
DevRadar nhận `403`, đồng thời tái sử dụng pipeline dữ liệu hiện có.

Trade-off: import là thao tác thủ công, chỉ có dữ liệu xuất hiện trong file và không thể tạo completeness
signal cho source.

### B. Lưu upload vào PostgreSQL queue rồi để crawler worker xử lý — không chọn

Queue giúp request ngắn và có thể retry, nhưng cần thêm entity, retention, cleanup, migration và raw-file
storage. File tối đa nhỏ và không có network nên chi phí này chưa được chứng minh.

### C. Browser extension tự gửi DOM hiện tại — defer

UX một click tốt hơn lưu file, nhưng thêm distribution/update surface, quyền extension và boundary tránh
cookie/session capture. Slice import file phải chứng minh parser/persistence trước khi nhận chi phí đó.

Server-side one-shot URL fetch bị loại vì trùng crawler hiện hành, vẫn bị `403`, đồng thời mở lại SSRF và
per-run URL override mà ADR-026 cấm.

## 4. Browser route correction

`validate_browser_route()` phân loại theo thứ tự:

1. parse URL và chặn scheme, credential, port, fragment hoặc path không hợp lệ;
2. nếu host không nằm trong persisted `allowed_hosts`, trả `allowed=false` mà không resolve DNS;
3. chỉ host đã allow-list mới được resolve qua pinned resolver và kiểm tra public address;
4. path ngoài persisted prefix trả `allowed=false`.

Trong Playwright routing:

- main-frame/document navigation hoặc redirect bị từ chối sẽ đặt `route_policy_blocked` và dừng preview;
- subresource bị từ chối chỉ bị abort, không đặt lỗi cho preview;
- host của script/image/font/analytics không trở thành route proposal;
- proposal cho job detail tiếp tục chỉ được suy ra từ candidate URL đã parse trong document.

Không thay đổi hard stop cho response `401/402/403`, challenge marker, popup, download, websocket hoặc
private/reserved target.

## 5. Document import contract

### 5.1. Endpoint

Thêm:

```text
POST /api/v1/source-recipes/{recipeId}/document-imports
Content-Type: multipart/form-data
Idempotency-Key: <8..128 chars>
file: <HTML | JSON | CSV>
```

Endpoint dùng cùng `LOCALHOST_SERVICE`, `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED`, origin/CSRF,
owner/session và rate-limit boundary của mutation `SourceRecipe`. Local no-login vẫn chỉ hợp lệ trên
localhost theo ADR-025. Recipe `retired` bị từ chối; notice `restricted_terms` hoặc `not_reviewed` phải
được acknowledgement đúng version trước import.

Request không nhận `documentUrl`, URL override, selector, header, cookie, proxy, credential hoặc code.
`SourceRecipe.listing_url` là base URL duy nhất để resolve relative link và recipe origin là source
boundary.

### 5.2. File validation

- tối đa `2 MiB` và không vượt `recipe.byte_budget`;
- chỉ UTF-8 text, cho phép UTF-8 BOM; reject NUL, invalid encoding, empty file và archive/binary;
- media type hợp lệ: `text/html`, `application/xhtml+xml`, `application/json`, `text/json`, `text/csv`;
- không tin filename/extension hoặc browser MIME riêng lẻ; nội dung phải parse đúng media type;
- HTML dùng parser hiện có, không render và không execute script/network;
- JSON dùng structured record/JSON-LD parser hiện có;
- CSV dùng `csv.DictReader` trong standard library, tối đa `500` row, `64` column và `64 KiB` mỗi cell.

CSV chấp nhận aliases hiện có cho `title|name`, `company|company_name|employer`,
`url|jobUrl|job_url|link|absolute_url`, cùng các field tùy chọn `id|external_id`, `location`,
`level|seniority`, `description` và `posted_at`. Candidate thiếu title, company hoặc HTTPS job URL bị
reject khỏi kết quả; import cần ít nhất một candidate hợp lệ.

Challenge document và malformed/over-complex input trả lỗi an toàn, không log body, row, HTML hoặc
filename chưa sanitize.

### 5.3. Route boundary cho candidate

Import không fetch candidate URL. Mỗi candidate vẫn phải là HTTPS, không credential/custom port và có
hostname đúng bằng recipe origin host. Path có thể nằm ngoài remote fetch prefix vì không có outbound
request; remote preview/crawl vẫn giữ nguyên path allow-list. Candidate sang host khác bị từ chối và
operator phải tạo recipe riêng cho host đó.

Quy tắc này cho phép listing/detail path khác nhau trên cùng TopCV hoặc Vieclam24h mà không nới route
policy của remote crawler.

### 5.4. Persistence và lifecycle

- parse và seniority filter chạy trước khi mở transaction ghi canonical data;
- first successful import tạo hoặc tái sử dụng `Source` `owner_authorized_local` của recipe;
- import không đổi `SourceRecipe.status`, `block_reason`, remote preview hash/ID hoặc enable gate;
- `CrawlRun.trigger=manual`; adapter/parser version phân biệt `source-recipe-document-import-v1`;
- mỗi candidate tạo `RawJobSnapshot` chứa canonical candidate JSON, field provenance, import document
  SHA-256 và media type; file upload gốc không được persist;
- `Job` và `JobChange` dùng pipeline source-scoped identity/content-hash hiện có;
- coverage luôn `incomplete`, kể cả file có vẻ chứa toàn bộ listing; vì vậy import không làm job thành
  `missing` hoặc `removed`;
- re-import cùng recipe/file/candidate không tạo thêm `Job` hoặc `JobChange` giả; một
  `RawJobSnapshot` mới vẫn được phép tồn tại để chứng minh input của từng `CrawlRun`.

Endpoint xử lý synchronous vì file không có network và đã bounded. Response trả data envelope chứa
`crawlRunId`, `jobsFound`, `jobsNew`, `jobsUpdated`, `jobsUnchanged`, `itemsFilteredOut`,
`coverage="incomplete"` và document hash rút gọn; không echo raw content.

### 5.5. Error contract

Các lỗi mới dùng envelope hiện hành:

- `document_import_disabled` (`404` để giữ feature boundary);
- `document_import_recipe_invalid` (`409`);
- `document_import_acknowledgement_required` (`409`);
- `document_import_too_large` (`413`);
- `document_import_type_unsupported` (`415`);
- `document_import_invalid` (`422`);
- `document_import_challenge_detected` (`422`);
- `document_import_no_jobs` (`422`);
- `document_import_route_blocked` (`422`);
- `idempotency_key_required|invalid|conflict` theo mutation contract hiện có.

## 6. Dashboard

Trong panel recipe được chọn, thêm card “Import file / Nhập tệp”:

- giải thích đây là import thủ công, không phải schedule hoặc bypass;
- accept `.html,.htm,.json,.csv`, hiển thị giới hạn `2 MiB`;
- disable với recipe retired, stale acknowledgement hoặc request đang chạy;
- sau thành công hiển thị found/new/updated/unchanged/filtered và link tới run/jobs;
- lỗi có copy Việt/Anh theo error code, không hiển thị stack/raw response;
- input file được reset sau success và không lưu nội dung vào browser storage.

Không thay đổi visual mapping hoặc remote preview controls trong slice này.

## 7. Threat boundaries

| Boundary | Abuse case | Control |
|---|---|---|
| Multipart upload | memory/CPU exhaustion | `2 MiB`, node/row/column/cell/candidate bounds, rate limit |
| HTML/JSON/CSV | script, formula, prompt injection | no execution, deterministic parser only, escaped React rendering |
| Candidate URL | SSRF/external host injection | no fetch; strict HTTPS + exact recipe-origin host |
| Duplicate request | duplicate jobs/changes | required idempotency key + source identity/content hash |
| Raw content | disclosure via log/response/storage | no raw file retention/log/echo; candidate snapshot only |
| Recipe lifecycle | upload used to enable blocked crawler | import never changes preview/enable state |
| Absence lifecycle | partial file removes unseen jobs | coverage always `incomplete` |

## 8. Verification

TDD coverage bắt buộc:

- external CDN subresource bị abort nhưng preview vẫn thành công;
- unapproved navigation/redirect, private target và allowed-host resolver failure vẫn hard block;
- valid HTML/JSON/CSV import tạo provenance chain `CrawlRun → RawJobSnapshot → Job`;
- same file re-import không tạo thêm job/change; changed candidate tạo đúng update/change;
- import không đổi blocked recipe hoặc remote preview/enable gate;
- incomplete import không tạo `missing`/`removed`;
- oversized, binary, invalid UTF-8, archive, malformed CSV/JSON/HTML, challenge page, cross-host URL,
  stale acknowledgement, retired recipe và duplicate idempotency-key conflict bị chặn;
- OpenAPI/BFF/UI VI/EN contracts, keyboard/file input accessibility và escaped text pass;
- focused tests trước, sau đó PostgreSQL integration, Python static gates, web check/build, Compose smoke,
  secret scan và final diff review.

Không tuyên bố TopCV/Vieclam24h tự động chạy theo lịch sau slice này. Acceptance thực tế là một file
được lưu từ trang operator mở bình thường có thể import thành canonical jobs với provenance và không có
outbound request.
