# Ingestion specification

## 1. Mục tiêu

Ingestion tạo dataset có thể tin cậy và replay từ các nguồn job công khai đã được phê duyệt. V1 ưu tiên ba source tại Việt Nam có identity ổn định; tên source chỉ được ghi vào registry sau khi vượt gate, không được chọn ngầm trong code.

## 2. Source approval gate

Một source chỉ chuyển từ `candidate` sang `approved` khi có record trả lời đầy đủ:

Danh sách discovery hiện tại nằm tại [Shortlist nguồn V1](sources/SHORTLIST.md). Shortlist chỉ ghi evidence và thứ tự review; nó không phải approval record và không cấp quyền chạy crawler.

### 2.1. Policy và phạm vi

- trang/feed/API có thể truy cập công khai, không cần đăng nhập hoặc token lấy bằng cách không được phép;
- robots policy và terms liên quan đã được review, ghi ngày và evidence URL/note;
- không cần bypass CAPTCHA, anti-bot, paywall hoặc access control;
- mục đích, tần suất và dữ liệu lưu phù hợp với quyền truy cập đã xác minh;
- có contact/takedown note để có thể pause source nhanh.

Review này là engineering gate, không phải tuyên bố tư vấn pháp lý. Khi điều khoản không rõ, giữ source ở `candidate` hoặc `paused`.

### 2.2. Kỹ thuật

- có stable `external_id` hoặc canonical URL được kiểm chứng;
- xác định được list/detail boundary và điều kiện run complete;
- có giới hạn request rate, concurrency, timeout, redirect và response size;
- parser có fixture đại diện và fixture malformed/empty;
- source có dữ liệu thật thuộc phạm vi job IT Việt Nam;
- browser chỉ cần khi HTTP/structured data không đủ;
- dữ liệu cần thiết không phụ thuộc vào bypass geo/account/private API.

### 2.3. Source registry record

Mỗi source approved phải ghi tối thiểu:

```yaml
name: example
base_url: https://careers.example.test
allowed_hosts:
  - careers.example.test
adapter_key: example
discovery_mode: html-list
identity_strategy: external_id
expected_pagination: complete
rate_limit:
  requests_per_minute: 10
  concurrency: 1
  timeout_seconds: 20
  max_response_bytes: 5000000
policy_review:
  status: approved
  robots_reviewed_at: YYYY-MM-DD
  terms_reviewed_at: YYYY-MM-DD
```

Đây là contract minh họa, không phải config chạy được và domain `.test` không phải source thật.

V1 implementation nằm tại [source registry](../src/devradar/ingestion/source_registry.py). Registry active chỉ có `vng-careers`, `naver-vietnam-greenhouse`, `momo-careers`; config copy đúng boundary trong từng approval record. Caller resolve bằng `source_key`, không truyền adapter key/URL. GeoComply/Lever không nằm trong active registry và giữ `candidate/permission_required`.

## 3. Crawler adapter boundary

Ba operation logic đủ cho V1:

```text
discover(run_context) -> stream of ListingRef
fetch(listing_ref, fetch_policy) -> FetchResult
parse(snapshot) -> ParsedJob | ParseFailure
```

### Input bắt buộc

- `run_context`: run ID, source config/version, deadline và correlation ID;
- `ListingRef`: source-scoped identity, approved URL và optional list-page metadata;
- `fetch_policy`: allowed hosts, timeout, byte limit, redirect limit, user-agent và throttle.

### Output bắt buộc

- `FetchResult`: final approved URL, HTTP metadata, fetch time, content type, bounded payload/reference và raw hash;
- `ParsedJob`: raw values, normalized candidates, evidence/selector, parser version và warnings;
- `ParseFailure`: stable error code, stage và safe summary; không chứa toàn bộ HTML hoặc secret.

Adapter không tự commit Job hoặc quyết định retry. Application workflow persist snapshot, validate output và điều khiển transaction/retry.

Contract code tại [ingestion contracts](../src/devradar/ingestion/contracts.py) dùng immutable typed input/output và stable `ParseFailure`; không trả ORM model, raw exception hoặc dynamic module path qua boundary.

### 3.1. Raw snapshot storage V1

V1 lưu text payload đã qua fetch limit trực tiếp trong PostgreSQL `RawJobSnapshot.raw_content`, cùng HTTP metadata và `raw_content_hash`. Fetcher reject payload vượt `max_response_bytes`, content type chưa duyệt hoặc content encoding khác `identity` trước persistence; schema `Text` không thay thế byte-limit control. Persistence revalidate final URL, approval/config version và strict-decode charset, tạo snapshot ở `parse_status=pending`, rồi chỉ `flush`; commit/rollback thuộc ingestion workflow caller. Raw column được deferred khi ORM query để read path không vô tình tải payload. Object storage chỉ được xem xét lại khi có số đo size/retention cho thấy PostgreSQL không còn phù hợp.

Implementation và verification hiện tại: [safe HTTP fetcher](../src/devradar/ingestion/safe_http.py), [snapshot persistence](../src/devradar/ingestion/snapshot_persistence.py) và [V1-004 evidence](evidence/V1-004-safe-fetch-and-snapshot.md).

## 4. Fetch policy

- Chỉ chấp nhận HTTPS URL được tạo từ source config/adapter, không nhận URL tùy ý từ API user; user-info, custom port, fragment, path/query control character và path ngoài prefix bị reject.
- Resolve toàn bộ địa chỉ host và fail closed nếu rỗng, invalid hoặc có bất kỳ loopback, link-local, private/reserved address nào.
- Kết nối trực tiếp tới numeric IP đã kiểm tra để tránh DNS resolve lần hai; TLS SNI và certificate validation vẫn dùng approved hostname.
- Revalidate scheme/host/path và resolve/pin lại mỗi redirect; không follow redirect ra ngoài boundary.
- Giới hạn socket timeout, redirect count và response bytes; body chỉ đọc tới `max_response_bytes + 1` để phát hiện overflow.
- Chấp nhận content type đã duyệt và content encoding `identity`; file/binary hoặc compressed response ngoài contract bị reject.
- Throttle theo source; default V1 là concurrency 1 trừ khi approval record có bằng chứng khác.
- V1 trả stable error code/retryability và bounded `Retry-After`; V2 workflow mới kích hoạt bounded retry/backoff có jitter.
- Không retry lỗi policy, invalid URL, unsupported content hoặc parser contract violation như lỗi network.
- User-Agent phải nhận diện hợp lý project/operator khi source policy yêu cầu; không giả mạo browser để bypass control.

### 4.1. Browser path

Khi approved source bắt buộc JavaScript rendering, browser không được nới lỏng fetch policy:

- validate scheme, host và resolved IP cho top-level navigation, redirect, iframe, subresource và WebSocket; network egress là lớp chặn cuối cho private/reserved destination;
- dùng fresh ephemeral browser context cho mỗi bounded run/batch, không tái sử dụng persistent profile, cookie, cache hoặc local storage giữa các source;
- chặn service worker, download, popup, external protocol và file URL; không cấp camera, microphone, geolocation, clipboard, notification hoặc filesystem permission;
- không mount secret/host directory không cần thiết vào browser runtime và chạy với sandbox/least privilege phù hợp platform;
- áp tổng budget cho page count, bytes, request count, execution time và browser process memory;
- đóng context/process và xóa temporary artifacts ở cả success, timeout và crash path.

### 4.2. NAVER Vietnam/Greenhouse HTTP adapter

V1 implementation tại [Greenhouse adapter](../src/devradar/ingestion/adapters/greenhouse.py) dùng đúng một `GET .../jobs?content=true` cho normal discovery. Adapter khóa literal board token `navervietnam`, kiểm tra `meta.total`, duplicate public post ID, Vietnam location và exact `absolute_url` trên reference host trước khi trả listing.

Greenhouse full-list response đã chứa content của từng post. Để không fan-out detail trái approval, `fetch(listing_ref, policy)` chỉ trả lại exact bounded `FetchResult` của discovery hiện tại; không mở request thứ hai. Cache bị xóa trước mỗi discovery attempt, chỉ chấp nhận exact listing đã validate và chạy dưới source concurrency 1. Workflow phải hoàn tất một discovery batch trước khi bắt đầu batch kế tiếp. Parser chọn job theo public post `id`, strip HTML thành plaintext, bỏ `script/style/template/noscript`, giữ raw JSON trong snapshot và không dùng `updated_at` như `posted_at`.

Fixture, negative path và bounded live evidence nằm tại [V1-006 evidence](evidence/V1-006-naver-greenhouse-adapter.md).

### 4.3. VNG Careers HTTP adapter

[VNG adapter](../src/devradar/ingestion/adapters/vng.py) chỉ discover qua public UI query `job_group=<approved-id>&page=<n>`. Registry pin tám cặp job-group ID/name đã duyệt; mỗi response phải tự xác nhận exact filter trong `request.queries` và cùng taxonomy trong `tags`. Broad `job_family` trên job card chỉ là provenance (`Tech`, `Data`, `Product` hoặc `null`), không được dùng để suy đoán scope IT.

Mỗi approved group được paginate cho tới `pages`, với page/size/total/count ổn định và unique `job_id`. Job xuất hiện trong nhiều approved group được source-scoped deduplicate khi URL/title không conflict. Chỉ sau khi toàn bộ groups complete, `fetch` mới nhận exact discovered listing và GET detail canonical trên VNG host. Detail parser dùng `job_id`, strip HTML, giữ description/requirement, redact email/phone khỏi canonical text và không diễn giải flag `post_on_careers_page` thành ngày đăng.

Fixture, live taxonomy regression và bounded page/detail smoke nằm tại [V1-007 evidence](evidence/V1-007-vng-adapter.md).

### 4.4. MoMo Careers browser adapter

[MoMo adapter](../src/devradar/ingestion/adapters/momo.py) chỉ navigate `GET /jobs-opening?groups=DGM.0001` trong fresh Chromium context. Batch đầu lấy từ SSR `__NEXT_DATA__`; khi chưa đủ `TotalItems`, adapter cách ít nhất 5 giây rồi click đúng public button `Xem thêm`, chờ exact response do UI tạo và đối chiếu response identities với DOM growth. Adapter không tự dựng/replay request API nền hoặc sửa `X-Client-*` header.

Browser route default-deny, chỉ cho list document, same-origin `/_next/static/` cần thiết và exact `aws.momo.vn/momovn-api/public/v2/hr/get-list-job-with-filter` query với approved group, sort, batch size và cumulative `lastIdx`. Trước launch, toàn bộ approved browser hosts phải resolve chỉ tới public IP. Context chặn service worker, download, popup và WebSocket; không cấp permission và không dùng persistent profile. Application-layer DNS/route controls không thay thế container/network egress policy, browser sandbox hoặc resource budget thuộc `V1-012`.

Completeness yêu cầu stable `TotalItems/PageCount`, mỗi UI batch thêm 1–12 unique `jobId`, `LastIndex` và DOM count tăng đúng cumulative count, final identities khớp response union và `Xem thêm` biến mất đúng khi đạt total. `Count=12` là requested batch size; final response có thể chứa ít hơn 12 `Items`, nên returned item count không được suy ra từ field này. Failed/partial attempt xóa discovery cache và không tạo missing/removal signal.

Detail chỉ fetch bằng `SafeHttpFetcher` cho exact canonical URL đã discover. Parser đối chiếu `jobId`, slug và fixed division group; chỉ giữ posting fields allow-list, strip unsafe HTML, bỏ application flags/related data và redact email/phone khỏi canonical description. Fixture, negative/browser-policy tests và full on-demand local evidence nằm tại [V1-008 evidence](evidence/V1-008-momo-adapter.md).

## 5. Extraction order

Thứ tự mặc định:

1. public feed/API hoặc JSON-LD có schema phù hợp;
2. HTTP HTML parser với stable selector/source rule;
3. browser rendering bằng Playwright khi source approval chứng minh cần JavaScript;
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

V1 implementation tại [Job upsert](../src/devradar/catalog/job_upsert.py) khóa row theo source-scoped external ID/canonical URL, ưu tiên external ID và fail closed nếu hai identity trỏ hai Job khác nhau. Function chỉ `flush`, không commit/rollback; create/update Job, snapshot `parse_status` và run counter nằm cùng transaction caller. Cùng snapshot replay không tăng counter; observation mới cùng hash chỉ cập nhật `last_seen_at/current_snapshot_id`; observation cũ hơn current state được đánh `stale` và không ghi đè. Chỉ `created/updated` tăng counter tương ứng; V1 reject Job đang ở absence state thay vì tự reactivation trước V2. Verification nằm tại [V1-009 evidence](evidence/V1-009-job-upsert.md).

### Khác source

- không auto-merge ở V1;
- fingerprint company/title/location hoặc embedding chỉ sinh `DuplicateCandidate` cùng score/reason;
- dữ liệu source riêng, source URL và lịch sử vẫn được giữ;
- chỉ merge khi một policy/review flow tương lai được đặc tả và kiểm thử.

## 8. Change detection và removal (V2)

V1 dùng `job_content_hash` để bỏ qua bản không đổi và cập nhật current canonical state khi content đổi, nhưng chưa giữ change history hoặc absence lifecycle. V2 kích hoạt `JobChange` và các state dưới đây.

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

Source chuyển `degraded` khi success rate/coverage hoặc parser signal vượt warning threshold đã baseline; chuyển `quarantined` khi lỗi liên tiếp có nguy cơ tạo dữ liệu sai hoặc vi phạm policy. Quarantine dừng schedule nhưng giữ history và cho operator review.

## 11. Metrics và audit

Mỗi run phải cung cấp:

- duration, request/page count và byte count;
- items discovered/fetched/parsed/valid/failed;
- jobs new/updated/unchanged/missing/removed/reactivated;
- retry count theo error code;
- parser/fallback usage và source health result;
- run/config/adapter version correlation.

Trong V1, các counter `missing`, `removed` và `reactivated` luôn bằng 0 vì lifecycle chưa được kích hoạt. Không dùng raw URL query chứa token, HTML, CV text hoặc response body làm metric label/log field.

## 12. Fixtures và acceptance scenarios

Mỗi source adapter cần fixture bất biến đã loại PII/token cho:

- list/detail happy path;
- pagination complete;
- empty but valid result;
- malformed hoặc unexpected HTML;
- missing optional field;
- duplicated listing;
- URL redirect ngoài allow-list;
- rate limit/timeout;
- source layout regression.

Acceptance bắt buộc:

1. Replay cùng fixture hai lần không tạo duplicate/change giả.
2. Partial run không tăng missing counter.
3. Từ V2, hai complete run vắng mặt tạo đúng `missing` rồi `removed`.
4. Từ V2, Job xuất hiện lại tạo `reactivated` và giữ history.
5. Source chưa approved không thể chạy dù adapter tồn tại.
6. Browser/LLM không được gọi khi structured parser đã đủ schema.
