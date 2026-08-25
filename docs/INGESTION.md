# Ingestion specification

## 1. Mục tiêu

Ingestion biến listing URL do owner local chọn thành dataset replayable có provenance mà không yêu cầu viết
adapter riêng. Runtime hiện hành theo [ADR-026](decisions/0026-accept-owner-overridden-source-recipes.md):
một generic `SourceRecipe`, deterministic extraction trước, browser fallback có kiểm soát sau và không
bypass technical access barrier.

## 2. Source Recipe onboarding gate

`SourceRecipe` chỉ bật khi deployment là `LOCALHOST_SERVICE` và
`DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED=true`. Catalog mười nguồn chỉ cung cấp listing hint và evidence cho
`terms_notice`; catalog không phải approval, permission hoặc source-specific implementation. URL ngoài
catalog nhận notice `not_reviewed`.

### 2.1. Terms notice và owner acknowledgement

- `terms_notice` có `not_reviewed`, `no_specific_restriction_found` hoặc `restricted_terms`, cùng version,
  review date và evidence URL khi có;
- notice luôn hiển thị. Recipe cần acknowledgement thì chỉ chấp nhận exact current version;
- khi catalog đổi notice version, recipe luôn yêu cầu owner review/xác nhận exact version mới trước khi
  preview/enable/run; persisted notice/evidence/review timestamp và Source review date được cập nhật cùng
  transaction;
- owner acknowledgement cho phép tiếp tục bounded local preview/crawl nhưng không phải permission hoặc
  legal certification;
- CAPTCHA, authentication, paywall, anti-bot, access denial, robots/access control, SSRF và redirect escape
  không thể được acknowledgement hoặc cấu hình để bypass; DevRadar không bypass các barrier này.

### 2.2. Technical gate

- URL phải là bounded HTTPS URL, không user-info/custom port/fragment/control character/dot-segment;
  raw/encoded separator, backslash, double slash, invalid/double percent encoding bị reject trước prefix
  matching và trước mọi redirect/pagination request tiếp theo;
- host/path/query được normalize và persist; tối đa ba host, không nhận URL/config override theo từng run;
- preview phải trả 3–5 distinct valid jobs hoặc hoàn tất visual mapping trước `enabled`;
- item/page/request/byte/time/rate budgets và concurrency 1 là invariant;
- schedule chỉ có `manual`, `every_6_hours`, `daily`, `weekly`; không nhận arbitrary cron.

## 3. Generic crawler boundary

```text
SourceRecipe -> preview(document) -> candidates | mapping_required | blocked
SourceRecipe + saved mapping -> discover() -> ListingRef + DiscoverySummary
fetch(ListingRef, FetchPolicy) -> FetchResult
parse(snapshot) -> ParsedJob | ParseFailure
```

Input luôn được sinh từ recipe đã persist: run ID, config hash/version, deadline, allowed host/path,
seniority, mapping và budget. `ListingRef` giữ source-scoped identity + canonical URL. Output gồm bounded
`FetchResult`, typed `ParsedJob`/`ParseFailure` và `DiscoverySummary(items_discovered,
items_filtered_out, pages_found, coverage_complete)`. Adapter không tự commit Job hoặc quyết định retry.

### 3.1. Preview và visual mapping

Preview là non-canonical và không tạo `CrawlRun`, snapshot, Job hoặc JobChange. Extraction order là
structured JSON/JSON-LD → deterministic HTML cards → isolated Playwright capture. Nếu browser detection
không đủ tin cậy, API chỉ trả screenshot bounded và opaque element IDs; UI không nhận CSS selector, raw
HTML hay script. Saved mapping được revalidate theo origin, artifact expiry và element map trước khi dùng.

Cross-host detail route chỉ được đề xuất từ canonical job URL của 3–5 candidate đã validate. Preview không
fetch detail URL trước xác nhận và không dùng browser subresource, CDN, font hoặc analytics host làm
proposal. UI hiển thị exact host/path, không có textbox tùy ý; owner chỉ có thể xác nhận exact union với
boundary đã lưu. Xác nhận reset recipe về `draft` rồi queue fresh preview. DNS/IP/path/redirect policy tiếp
tục fail closed ở lần fetch sau; tổng boundary tối đa ba host và mười path prefix.

Disposition public không lộ lỗi parser/transport nội bộ:

- browser artifact có screenshot non-empty và element map dùng được nhưng chưa đủ ba job trả
  `mapping_required`, giữ recipe ở `draft` để owner sửa mapping;
- nội dung/layout không tạo được candidate hoặc visual artifact hợp lệ trả `layout_unavailable` và
  chuyển recipe sang `blocked`;
- DNS/network/TLS/`5xx` transient được gom thành `source_unavailable`, giữ recipe ở `draft` để retry sau;
- `rate_limited` dùng cooldown; access barrier và route policy tiếp tục trả hard-stop code riêng.

### 3.2. Raw snapshot storage

PostgreSQL giữ bounded `RawJobSnapshot.raw_content`, HTTP metadata, canonical provenance URL và
`raw_content_hash`. Fetcher reject payload/content type/encoding ngoài policy trước persistence. Persistence
revalidate final URL/config và strict-decode charset; transaction ownership thuộc workflow caller. Raw
column được deferred khi query để read path không tải payload ngầm.

### 3.3. Local document import

Khi remote preview/crawl bị access denial nhưng operator đã lưu trang hợp lệ cục bộ, endpoint document
import nhận đúng một tệp UTF-8 HTML, JSON hoặc CSV tối đa `2 MiB` và không vượt recipe byte budget. CSV
dùng `DictReader` standard library với tối đa `500` row, `64` column và `64 KiB` mỗi cell. Archive, binary,
NUL, invalid UTF-8, empty/malformed/challenge content và candidate không có HTTPS URL đúng recipe hostname
bị reject trước canonical persistence.

Import không outbound request, không render/execute HTML/script và không lưu file gốc. Nó chỉ persist
canonical candidate JSON cùng field provenance, media type và document SHA-256 trong `RawJobSnapshot`, rồi
tái sử dụng source-scoped normalization, content hash, `Job` và `JobChange`. Idempotency key reuse với cùng
request trả lại run hiện hữu; reuse với document/config khác là conflict.

Mọi imported run có `coverage=incomplete`: import không tạo `missing` hoặc `removed`, không thay đổi remote source health,
failure/quarantine/baseline/timestamp và không thay đổi recipe preview/block/enable state.
Import không cấp schedule cho file và không chứng minh remote crawler truy cập được source.

## 4. Fetch, pagination và browser policy

- Resolve toàn bộ DNS và fail closed nếu có loopback/link-local/private/reserved address; HTTP pin mỗi
  request/redirect. Browser resolve toàn bộ allowed host trước launch, ưu tiên một public IPv4 khi có cả hai
  family, map hostname sang exact validated IP (IPv6 dùng bracket syntax), fail mọi hostname khác và tắt
  system proxy; navigation/subrequest vẫn revalidate host/path qua pinned resolver.
- Giới hạn timeout, redirect, bytes, page/item/request/time/rate; content encoding mặc định `identity`.
- HTTP/structured data luôn chạy trước. Browser dùng fresh context, chặn service worker/download/popup/
  external protocol/WebSocket/permission và không có cookie, credential hoặc persistent profile.
- Generic pagination chỉ dùng saved stable next-page/numbered/load-more target trong cùng policy boundary;
  loop, unstable load-more, deadline hoặc budget stop làm coverage `incomplete`.
- Detail chỉ fetch canonical URL đã discover. Seniority filter deterministic; item không xác định bị loại
  khi chọn level cụ thể và được giữ khi chọn `all`.
- `401/402/403`, login form, CAPTCHA/challenge, paywall, anti-bot marker hoặc route escape đưa recipe tới
  `blocked`, không retry và không có bypass action.

### 4.1. Recipe worker và transaction boundary

`python -m devradar.cli source-recipe-worker` chỉ claim preview/run đã persist trong PostgreSQL. Network/
browser work chạy ngoài transaction dài; snapshot, canonical upsert và counters dùng transaction ngắn.
Fixed schedule và manual request có idempotency key; nhiều worker dùng row lock `SKIP LOCKED`.

Mỗi pending run bind full recipe config hash gồm URL, host/path, field/pagination mapping, seniority,
parser/config version, item/page/request/byte/time/rate budget và terms notice version. Reuse manual
idempotency key sau config change là conflict. Nếu recipe bị pause/retire, notice drift hoặc config đổi
trước claim, worker atomically chuyển run thành `cancelled` với safe code rồi tiếp tục hàng đợi; run không
vào adapter, không retry và không tác động source health hay missing/removal lifecycle.

Generic empty/layout drift, partial item failure, pagination budget hoặc browser deadline luôn tạo coverage
`incomplete`. Chỉ run `succeeded + complete` mới là absence/removal signal.

## 5. Extraction order

Thứ tự mặc định:

1. public JSON/JSON-LD có schema phù hợp;
2. HTTP HTML card parser hoặc saved opaque mapping;
3. isolated browser rendering bằng Playwright khi HTTP không đủ;
4. LLM fallback từ V3 cho field còn thiếu, không dùng để điều khiển navigation.

Không chạy cả browser và LLM theo mặc định. Mỗi fallback phải ghi reason/metric để có thể thấy chi phí và regression.

## 6. Normalization

### Text

- decode theo charset có evidence, normalize Unicode và whitespace;
- giữ `*_raw` trước khi map sang canonical value;
- sanitize khi render, không xóa evidence trong storage chỉ để “làm sạch” UI;
- content hash loại bỏ volatile markup được chỉ rõ, không loại dữ liệu có ý nghĩa.

### URL và identity

- resolve relative URL theo approved base URL;
- chỉ bỏ tracking parameter đã có allow-list; không sort/remove parameter có thể là identity;
- external ID ưu tiên hơn URL khi source chứng minh ổn định;
- không dùng title/company hash làm auto identity V1.

### Location

- giữ `location_raw`;
- chuẩn hóa thành city/province/work mode chỉ khi mapping có confidence;
- không biến “Vietnam” thành Ho Chi Minh City hoặc suy ra remote nếu JD không nói.

### Salary

- giữ nguyên `salary_raw`;
- parse amount, min/max, ISO currency và period (`hour`, `month`, `year`) riêng;
- không đổi VND sang currency khác, không nhân/chia period nếu context không đủ;
- range lỗi, min lớn hơn max hoặc đơn vị mơ hồ phải bị reject/needs review.

### Level, experience và skill

- `level_raw`/`levels` và experience là field riêng; không suy “Senior” thành số năm nếu nguồn không nêu;
- từ V3, skill alias được map qua taxonomy có version và giữ raw mention/evidence;
- required/preferred/optional chỉ được gán khi câu chữ hỗ trợ.

V1 implementation tại [normalization module](../src/devradar/ingestion/normalization.py) giữ `raw/value/warnings`. Location alias chỉ gồm evidence đã có fixture; URL chỉ bỏ query key do caller allow-list; ký hiệu currency mơ hồ, range đảo và input thiếu unit bị reject/warn thay vì đoán. Skill V1 chỉ cleanup raw mention, chưa merge alias hoặc tạo taxonomy trước V3.

Canonical hash schema `job-content-v1` gồm source URL; title/company/description; location raw + structured; salary raw + structured; level raw + ordered levels; experience range. Fetch timestamp, run ID, selector và warning bị loại. Đổi field set/semantics phải tạo version mới và reprocessing plan.

## 7. Idempotency và deduplication

### Trong cùng source

- primary idempotency key: `(source_id, external_id)`;
- fallback đã duyệt: `(source_id, normalized_canonical_url)`;
- cùng identity và cùng `job_content_hash`: update observation/last seen, không tạo Job mới;
- cùng identity nhưng canonical hash khác: V1 transactionally update current Job và run counter; từ V2 mới tạo các JobChange có nghĩa.

Implementation tại [Job upsert](../src/devradar/catalog/job_upsert.py) khóa row theo source-scoped external ID/canonical URL, ưu tiên external ID và fail closed nếu hai identity trỏ hai Job khác nhau. Function chỉ `flush`, không commit/rollback; Job, JobChange, snapshot `parse_status` và run counter nằm cùng transaction caller. Cùng snapshot replay không tăng counter/event; observation mới cùng hash chỉ cập nhật `last_seen_at/current_snapshot_id`; observation cũ hơn current state được đánh `stale` và không ghi đè. Observation hợp lệ mới hơn reactivation Job `missing/removed` và giữ event provenance. Verification: [V1 upsert](evidence/V1-009-job-upsert.md), [V2 lifecycle](evidence/V2-003-job-change-and-absence-lifecycle.md).

### Khác source

- không auto-merge ở V1;
- fingerprint company/title/location hoặc embedding chỉ sinh `DuplicateCandidate` cùng score/reason;
- dữ liệu source riêng, source URL và lịch sử vẫn được giữ;
- chỉ merge khi một policy/review flow tương lai được đặc tả và kiểm thử.

## 8. Change detection và removal (V2)

V1 dùng `job_content_hash` để bỏ qua bản không đổi và cập nhật current canonical state. V2 hiện giữ `JobChange` và kích hoạt các state dưới đây.

Field có thể tạo change event ban đầu: title, company representation, location/work mode, salary, level set/experience, description canonical text, skill set, source URL và status.

Không tạo change cho timestamp fetch, selector metadata, tracking parameter, whitespace hoặc markup không làm đổi canonical content.

Quy trình vắng mặt:

1. Chỉ xét absence sau run `succeeded` với coverage `complete`.
2. Lần complete đầu không thấy Job: `active → missing`, counter = 1.
3. Lần complete kế tiếp vẫn không thấy: `missing → removed`, mặc định counter = 2.
4. Thấy lại ở bất kỳ run hợp lệ nào: `missing/removed → active`, reset counter và tạo `reactivated` event.
5. Failed/partial/cancelled/unknown coverage không thay status hoặc counter.

Source có thể dùng threshold cao hơn nếu approval record ghi lý do; không được thấp hơn default nếu thiếu evidence. Explicit 404 trên detail URL là observation hữu ích nhưng vẫn phải tuân source-specific completeness policy để tránh false removal.

## 9. Run completeness

Run chỉ là complete khi adapter chứng minh đã đi hết pagination/feed boundary dự kiến và không có lỗi làm mất một phần không xác định của listing set. Ví dụ làm run `partial`:

- page giữa chuỗi pagination fail sau retry;
- source trả response bất thường/rỗng so với invariant;
- browser timeout trước khi xác nhận end state;
- parser reject vượt ngưỡng safety;
- deadline/cancellation trước khi hoàn tất.

Số job giảm mạnh không tự động chứng minh source đã xóa job; nó kích hoạt anomaly/degraded signal và ngăn removal nếu coverage đáng ngờ.

## 10. Retry, quarantine và health

Error taxonomy tối thiểu:

- `network_timeout`, `dns_failure`, `rate_limited`, `server_error` — transient;
- `policy_blocked`, `redirect_blocked`, `response_too_large` — safety/policy;
- `unexpected_content`, `parse_contract_failed`, `coverage_unknown` — adapter/data;
- `persistence_failed`, `cancelled` — platform/operator.

V2 kích hoạt orchestration retry. Policy khởi điểm: tối đa ba attempt cho transient failure, exponential backoff có jitter và tôn trọng `Retry-After`. Không retry tự động lỗi policy hoặc dữ liệu invalid.

Implementation V2 giữ trigger key, UTC schedule slot, attempt và retry relation trong `CrawlRun`. PostgreSQL partial unique index giới hạn một active run mỗi source và một run cho mỗi source/trigger key. Duplicate process không được giải quyết bằng in-memory lock vì CLI, API và scheduler có thể là process khác nhau.

Source dùng median tối đa năm complete successful run làm inventory baseline. Gate chỉ bật sau ít nhất hai baseline run; current inventory dưới 50% baseline tạo `inventory_drop_anomaly`, hạ coverage thành `incomplete` trước absence lifecycle và chuyển Source `degraded`. Complete recovery run cập nhật baseline/reset failure.

Policy/safety failure quarantine ngay. Data/layout failure đầu chuyển `degraded`, lần liên tiếp thứ hai quarantine. Transient failure chỉ chuyển `degraded` rồi `unhealthy` từ ba lần liên tiếp; platform failure chuyển `unhealthy`. Quarantine dừng scheduled/retry trigger nhưng giữ history và cho manual operator recheck; chỉ complete success mới phục hồi.

## 11. Metrics và audit

Mỗi run phải cung cấp:

- duration, request/page count và byte count;
- items discovered/fetched/parsed/valid/failed;
- jobs new/updated/unchanged/missing/removed/reactivated;
- retry count theo error code;
- parser/fallback usage và source health result;
- run/config/adapter version correlation.

Từ V2, `missing`, `removed` và `reactivated` được persist/log bằng bounded counter; JobChange không được copy description đầy đủ vào structured log. Không dùng raw URL query chứa token, HTML, CV text hoặc response body làm metric label/log field.

## 12. Fixtures và acceptance scenarios

Generic recipe parser/adapter cần fixture bất biến đã loại PII/token cho:

- list/detail happy path;
- pagination complete;
- empty but valid result;
- malformed hoặc unexpected HTML;
- missing optional field;
- duplicated listing;
- URL redirect ngoài allow-list;
- rate limit/timeout;
- source layout regression, challenge/login/paywall marker và visual mapping expiry/tampering.

Acceptance bắt buộc:

1. Replay cùng fixture hai lần không tạo duplicate/change giả.
2. Partial run không tăng missing counter.
3. Từ V2, hai complete run vắng mặt tạo đúng `missing` rồi `removed`.
4. Từ V2, Job xuất hiện lại tạo `reactivated` và giữ history.
5. Recipe chưa preview/current acknowledgement không thể enable hoặc crawl.
6. Browser/LLM không được gọi khi structured parser đã đủ schema.
7. Unknown-origin recipe dùng `not_reviewed`; restricted catalog source cần exact-version owner acknowledgement.
8. Challenge/login/paywall/403 fixture đi tới `blocked` và UI không có bypass action.
9. Generic empty/layout drift, failed hoặc partial run không tạo false removal.
10. HTML/JSON/CSV import hợp lệ tạo provenance; replay idempotent, changed candidate tạo đúng change.
11. Import oversized/binary/invalid/challenge/cross-host/stale acknowledgement/retired bị chặn an toàn.
12. Import luôn incomplete, không đổi remote health/lifecycle và không live-fetch URL trong file.

Source-specific adapter/evidence cũ được giữ trong Git history và historical ADR/evidence, không phải runtime
contract hiện hành. Acceptance V6-020 dùng cùng generic implementation cho URL catalog và URL ngoài catalog;
không thêm adapter khi một source layout khác.
