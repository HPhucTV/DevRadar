# DevRadar No-code Source Recipe Design

## Mục tiêu

Thay toàn bộ crawler source-specific và flow Custom Sources hiện tại bằng một trải nghiệm
single-operator không cần code:

1. dán URL trang danh sách hoặc kết quả tìm kiếm việc làm;
2. chọn seniority cần lấy;
3. xem preview 3–5 job;
4. sửa nhận diện bằng cách click trực tiếp trên ảnh trang web khi cần;
5. chạy ngay hoặc đặt lịch;
6. đưa dữ liệu hợp lệ vào pipeline provenance/idempotency/change detection hiện có.

Capability này chỉ hoạt động trong `LOCALHOST_SERVICE`. Nó không phải public arbitrary-fetch API,
không lưu credential của website và không vượt CAPTCHA, authentication, paywall, anti-bot hoặc access
control.

## Quyết định sản phẩm đã chốt

- Input là URL của trang listing/search result, không phải homepage chung.
- Seniority multi-select gồm `all`, `intern`, `fresher`, `junior`, `mid`, `senior`, `lead`,
  `manager`; `all` là mặc định và loại trừ các lựa chọn còn lại.
- Preview 3–5 job hợp lệ là bắt buộc trước khi recipe được enable.
- Auto-detection sai thì owner click lần lượt job card, title, company, location và next/load-more
  control trên screenshot có overlay. UI không hiển thị CSS selector, XPath hoặc code.
- `title`, `company` và canonical job URL là field bắt buộc. `location` có thể được đánh dấu là
  không có. Next/load-more là optional nếu inventory chỉ có một trang.
- Schedule chỉ gồm `manual`, `every_6_hours`, `daily` và `weekly`; không mở arbitrary cron.
- VNG, MoMo, NAVER/Greenhouse, RemoteJobs.org và `CustomSourceAdapter` hiện tại bị loại khỏi active
  runtime, registry, UI, command và test surface.
- Mọi source-derived data hiện có bị purge ở đầu implementation, không backup, theo lựa chọn rõ ràng
  của owner. Dashboard trống trong thời gian xây replacement là accepted.
- Source có điều khoản hạn chế automated collection vẫn có thể được owner-local preview/crawl sau
  explicit acknowledgement. Đây là owner override, không phải legal certification.
- CAPTCHA, login, paywall, anti-bot challenge, access denial hoặc cơ chế kỹ thuật hạn chế truy cập vẫn
  là hard stop và không có action bypass.

## Thay đổi source policy

### Terms là cảnh báo, không phải runtime gate

`permission_required` không còn là hard-block status cho no-code recipe. Thay vào đó, mỗi domain có
`terms_notice`:

- `not_reviewed`: chưa có review đáng tin cậy;
- `no_specific_restriction_found`: review chưa thấy cấm automation rõ ràng;
- `restricted_terms`: review thấy điều khoản hạn chế hoặc yêu cầu written permission.

`terms_notice` luôn được hiển thị cùng source URL, evidence link và ngày review. Với
`not_reviewed` hoặc `restricted_terms`, owner phải xác nhận cảnh báo cho exact normalized origin trước
preview đầu tiên. Acknowledgement lưu `owner_id`, origin, notice version, evidence URL và timestamp;
không được dùng để claim website đã cho phép.

Owner acknowledgement cho phép local crawler tiếp tục tới technical preview ngay cả khi
`terms_notice=restricted_terms`. Nó không thay đổi hoặc che nội dung cảnh báo.

### Technical access vẫn fail-closed

Các trường hợp sau dừng preview/run và đưa recipe về `blocked` với safe `block_reason`:

- `authentication_required`: login, session hoặc credential bắt buộc;
- `payment_required`: paywall hoặc HTTP `402`;
- `access_denied`: HTTP `401`, `403`, proxy denial hoặc equivalent denial page;
- `challenge_detected`: CAPTCHA, bot challenge, browser verification hoặc interstitial tương tự;
- `route_policy_blocked`: SSRF, unsafe DNS/IP, redirect hoặc request ra ngoài saved boundary;
- `unsupported_interaction`: website cần thao tác phức tạp hơn listing/detail/next/load-more đã lưu;
- `layout_unavailable`: không thể tạo preview 3 job hợp lệ sau auto-detection và visual correction.

HTTP `429` tạo `rate_limited` cooldown theo bounded `Retry-After`; không retry ngay để né giới hạn.
Future scheduled run chỉ được chạy sau cooldown. Network/`5xx` transient dùng retry policy hiện có;
challenge/access denial không retry.

## Source catalog ban đầu

Catalog là dữ liệu versioned để hiển thị notice và canonical listing hint; nó không chứa adapter riêng.
Kết quả review ngày 2026-08-24:

| Source | Terms notice ban đầu | Technical disposition |
|---|---|---|
| [ITviec](https://itviec.com/blog/terms-and-conditions/) | `restricted_terms` | Cho owner override rồi bounded preview |
| [TopDev](https://topdev.vn/term-of-services) | `no_specific_restriction_found` | Bounded preview candidate |
| [VietnamWorks](https://www.vietnamworks.com/robots.txt) | `not_reviewed` | Owner acknowledgement rồi bounded preview |
| [TopCV](https://www.topcv.vn/terms-of-service) | `restricted_terms` | Cho owner override rồi bounded preview |
| [Glints](https://glints.com/vn/about/terms) | `restricted_terms` | Cho owner override rồi bounded preview |
| [CareerViet](https://careerviet.vn/vi/jobseekers/use) | `restricted_terms` | Cho owner override rồi bounded preview |
| [JobsGO](https://jobsgo.vn/site/term-of-service) | `restricted_terms` | Cho owner override; access challenge vẫn hard stop |
| [Indeed Vietnam](https://www.indeed.com/legal) | `restricted_terms` | Cho owner override rồi bounded preview |
| [CareerLink](https://www.careerlink.vn/thoa-thuan-su-dung) | `restricted_terms` | Cho owner override rồi bounded preview |
| [Vieclam24h](https://vieclam24h.vn/dieu-khoan-su-dung.html) | `no_specific_restriction_found` | Bounded preview candidate |

Evidence review phải trỏ tới trang official terms/robots. Catalog không hứa source sẽ technically
previewable tại thời điểm chạy; response/challenge hiện tại mới là runtime evidence.

URL từ domain ngoài catalog vẫn được tạo recipe với `terms_notice=not_reviewed`, explicit owner
acknowledgement và cùng technical boundaries. User không cần tự viết adapter hoặc selector.

## Trải nghiệm người dùng

### 1. Tạo recipe

Trang `Sources` có một form chính:

- `Listing URL`;
- seniority multi-select;
- nút `Preview jobs`;
- notice terms/policy theo domain;
- acknowledgement checkbox khi notice yêu cầu.

Known-source card chỉ là shortcut điền listing URL và hiển thị trạng thái; không có adapter riêng.
URL phải là HTTPS, không có user-info, fragment hoặc custom port. Homepage không bị chặn chỉ dựa trên
path, nhưng preview sẽ fail nếu không phát hiện tối thiểu ba job distinct.

### 2. Preview tự động

Preview chạy async trong crawler service và UI poll bounded status. Kết quả thành công hiển thị 3–5
job cards với:

- title, company, location nếu có;
- canonical job URL;
- detected seniority;
- confidence và provenance dạng dễ hiểu (`structured data`, `page field`, `manual mapping`);
- warnings về field thiếu, duplicate, filtered-out item hoặc coverage chưa biết.

Preview không tạo `CrawlRun`, `RawJobSnapshot`, `Job`, `JobChange`, embedding hoặc removal signal.

### 3. Visual correction

Khi auto preview không đạt gate, UI mở screenshot tĩnh của trang listing trong overlay mapper. Owner
chọn theo wizard:

1. một job card mẫu;
2. title trong card;
3. company;
4. location hoặc `Source does not provide location`;
5. job link;
6. next-page/load-more control hoặc `Single page`.

Browser worker lưu candidate DOM nodes bằng opaque `element_id`. Frontend chỉ gửi `preview_id` và
selected element IDs; backend resolve thành structural mapping nội bộ rồi chạy preview mới. Element
ID hết hạn cùng preview và không được tái sử dụng giữa origin/page khác.

Screenshot là WebP/PNG bounded, loại URL query khỏi metadata, tối đa 1.5 MiB. Element map tối đa 200
nodes và preview artifact hết hạn sau 24 giờ. Với quy mô single-operator, screenshot + map được lưu
temporary trong PostgreSQL để không thêm object storage hoặc Redis.

### 4. Enable và vận hành

Sau preview thành công, owner chọn:

- `Crawl now`;
- mỗi 6 giờ;
- hằng ngày tại local time, mặc định `09:00`;
- hằng tuần tại weekday/local time, mặc định thứ Hai `09:00`.

Recipe lưu timezone IANA, mặc định `Asia/Ho_Chi_Minh`. Mỗi recipe chỉ có một active run. Manual và
scheduled trigger dùng idempotency key/slot hiện hành.

## Domain model

### SourceRecipe

`SourceRecipe` thay `CustomSourceProfile` và là cấu hình duy nhất cho generic crawler:

| Nhóm | Field logic |
|---|---|
| Identity | `id`, `owner_id`, `name`, `source_id` |
| Boundary | normalized `listing_url`, origin, allowed hosts/path prefixes |
| Notice | `terms_notice`, notice version/evidence, owner acknowledgement |
| Extraction | parser version, internal field mapping, pagination mapping |
| Filter | ordered `seniority_filter`; empty không hợp lệ, `all` đứng một mình |
| Schedule | kind, local time/weekday, timezone, `next_run_at` |
| Preview | latest successful preview ID/hash/mapping version |
| State | status, block reason, cooldown, timestamps |
| Budgets | item/page/request/byte/time/rate limits |

Recipe status giữ một state machine nhỏ:

```text
draft -> previewing -> preview_ready -> enabled
           |              |              |
         blocked        retired         paused
                                           |
                                         enabled
```

`blocked` và `draft` phải preview lại. `retired` là terminal. Terms notice không nằm trong state
machine vì nó là disclosed owner decision, không phải technical health.

### SourceRecipePreview

Preview session có `pending`, `running`, `succeeded`, `failed`, expiry, safe error, candidate jobs,
screenshot và opaque element map. Nó không dùng `CrawlRun` để tránh làm nhiễu ingestion history và
không bao giờ là completeness/removal evidence.

### Source và Job

Mỗi enabled recipe sở hữu một `Source` có `approval_status=owner_authorized_local`. Global `approved`
không còn source implementation active sau reset. Job, snapshot và run vẫn giữ provenance về Source
và recipe mapping/config version.

Source identity của recipe dựa trên persisted recipe ID, không dựa chỉ vào hostname. Hai recipe trên
cùng domain nhưng khác listing/filter là hai Source riêng để completeness và missing/removal không
trộn nhau.

## Extraction và crawl pipeline

```text
URL + seniority + owner acknowledgement
  -> policy/SSRF preflight
  -> PostgreSQL preview queue
  -> HTTP structured-data detection
  -> isolated Playwright fallback khi cần render JS
  -> automatic candidate mapping
  -> optional screenshot correction
  -> validated preview 3–5 jobs
  -> persisted SourceRecipe mapping
  -> Crawl now / PostgreSQL scheduler
  -> bounded listing/detail/pagination traversal
  -> snapshot + normalization + source-scoped upsert
  -> change detection, health and derived-data jobs
```

Extraction order là deterministic:

1. JSON-LD `ItemList`/`JobPosting` hoặc structured JSON embedded trong trang;
2. semantic link/card/heading heuristics;
3. saved visual mapping;
4. browser rendering chỉ khi HTTP result không đủ và route đã qua policy.

Không dùng LLM để tự viết selector, điều khiển browser hoặc quyết định access policy. HTML/JD là
untrusted input và không được thay đổi budgets, allowed hosts, mapping flow hoặc tool policy.

### Pagination và detail URLs

V1 của recipe engine hỗ trợ:

- link `next`/numbered page;
- query/path page increment được quan sát từ page control;
- một load-more button có bounded request/navigation behavior;
- job detail links.

Listing origin là primary boundary. Host detail/pagination bổ sung chỉ được lưu khi preview quan sát,
HTTPS + DNS/IP policy pass và owner xác nhận danh sách domain dễ đọc; tối đa ba hosts mỗi recipe.
Redirect ở mỗi run vẫn được revalidate. Không nhận arbitrary headers, cookies, proxy, DNS hoặc URL
override theo run.

Unsupported multi-step form, infinite interaction không có stable load-more, websocket-only private
feed hoặc credential flow trả `unsupported_interaction`; user không phải viết code để xử lý.

### Seniority filter

Classifier dùng source field rõ ràng trước, rồi token/phrase deterministic từ title và labeled
metadata. Vietnamese/English aliases được version hóa bằng fixture. Không suy ra seniority chỉ từ số
năm kinh nghiệm khi title/source không có evidence.

- `all`: giữ mọi job, kể cả seniority chưa xác định;
- filter cụ thể: chỉ persist job có ít nhất một level giao với lựa chọn;
- ambiguous/unknown bị bỏ qua và tăng `items_filtered_out`, không được gán level giả.

Filtering xảy ra trước canonical upsert. Run summary tách discovered, filtered, valid và persisted để
operator hiểu vì sao count thấp.

## API contract định hướng

REST JSON tiếp tục nằm dưới `/api/v1`; OpenAPI từ FastAPI là wire contract chính:

```text
GET    /api/v1/source-catalog
GET    /api/v1/source-recipes
POST   /api/v1/source-recipes
GET    /api/v1/source-recipes/{recipeId}
PATCH  /api/v1/source-recipes/{recipeId}
DELETE /api/v1/source-recipes/{recipeId}
POST   /api/v1/source-recipes/{recipeId}/previews
GET    /api/v1/source-recipes/{recipeId}/previews/{previewId}
POST   /api/v1/source-recipes/{recipeId}/previews/{previewId}/mapping
GET    /api/v1/source-recipes/{recipeId}/crawl-runs
POST   /api/v1/source-recipes/{recipeId}/crawl-runs
```

Create nhận listing URL, name, seniority, schedule và acknowledgement fields đã validate. Crawl-run
mutation không nhận URL/header/mapping override. Screenshot được trả dạng bounded data URL trong JSON
preview response để giữ API JSON-only và tránh thêm artifact service.

Các endpoint `/api/v1/custom-sources` và BFF tương ứng bị xóa theo hard-cut migration; project chưa
phát hành compatibility promise cho API này. Error code và lifecycle mới phải được cập nhật đồng thời
trong `docs/API.md`, OpenAPI contract tests và dictionary VI/EN.

## Security, privacy và observability

- `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED=false` mặc định.
- Feature chỉ hợp lệ với `DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE`; protected/public startup phải
  reject nếu bật.
- Same-origin BFF, local operator ownership và mutation Origin/JSON/rate-limit checks vẫn áp dụng.
- Browser dùng fresh ephemeral context, không credential/cookie/profile reuse; chặn download, popup,
  external protocol, service worker và private/reserved network destination.
- Browser chỉ chạy trong hardened crawler container; API container không cài/launch Chromium.
- Mỗi request/redirect revalidate scheme, hostname, resolved IP và saved route boundary.
- Log chỉ chứa recipe/source/run/preview ID, normalized hostname, safe error, count, duration và version;
  không chứa full query, raw HTML, screenshot bytes, cookies, token hoặc JD text.
- Screenshot/DOM artifact bị purge sau 24 giờ; raw snapshots/canonical jobs theo retention hiện hành.
- Recipe source không được dùng cho public market claim nếu chưa có cohort/coverage evidence.

Metrics tối thiểu: preview/run duration, request/page/byte count, parser path, browser fallback,
detected/mapped/filtered/valid/persisted count, challenge/block reason, schedule lag và layout drift.

## Destructive reset và deprecation

Reset là intentional hard cut, không phải dual-run migration.

### Dữ liệu bị purge, không backup

Trong một transaction, migration xóa source-derived graph theo dependency-safe order:

- alert deliveries và JobMatch gắn Job;
- extraction/classification/summary/skill-mention/embedding derived rows;
- JobChange, Job và RawJobSnapshot;
- CrawlRun và source health/history;
- `CustomSourceProfile` cùng schedule/preview state cũ;
- Source records của VNG, MoMo, NAVER/Greenhouse, RemoteJobs.org và custom sources.

`AuthUser`, `AuthSession`, local operator, `ResumeProfile`, standalone AlertRule và deployment settings
được giữ. Resume/job match results bị xóa vì Job bị purge. Skill taxonomy/version có thể giữ nếu nó
không chứa source-derived observation.

Ngay trước destructive transaction phải re-count exact tables/source keys, xác nhận database target
không phải unexpected host và ghi safe count-only evidence. Không tạo backup theo quyết định của owner.
Migration/operation fail thì rollback toàn transaction. Downgrade không thể phục hồi data đã purge và
phải nói rõ điều này.

### Code và tài liệu bị loại

- source-specific adapter/runtime registry/config/fixtures/tests/CLI path;
- `devradar.custom_sources`, `CustomSourceAdapter`, API/BFF/UI/dictionaries cũ;
- custom-source worker command/config flag và active README/Operations instructions;
- active source counts/showcase claims dựa trên dataset đã purge.

Historical migrations, ADR và evidence không bị sửa để che lịch sử. ADR mới supersede ADR-004 và phần
permission hard-block của ADR-024; historical documents được gắn rõ `Superseded`, không còn là current
runtime contract.

## One-click local startup

Root `start-devradar.cmd` gọi một PowerShell orchestrator nhỏ, tái sử dụng Compose/deploy scripts hiện
có:

1. kiểm tra Docker/Compose;
2. dùng `.env` nếu tồn tại, nếu không tạo từ safe local template bị Git ignore;
3. bật explicit localhost no-login và local source-recipe feature;
4. build/start database, migrate, API, web và crawler worker;
5. chạy API/web smoke;
6. mở `http://127.0.0.1:3000` khi healthy.

Launcher không tự crawl URL chưa enable. Scheduler chỉ enqueue recipe đã enabled và đến hạn. Script
không xóa volume, không ghi secret vào console/Git và khi lỗi phải giữ cửa sổ với hướng dẫn ngắn.
README cập nhật một-click path cùng manual fallback commands đã kiểm chứng.

## Failure handling

- Preview dưới 3 distinct valid jobs: `preview_insufficient_jobs`, giữ `draft`.
- Mapping ID sai origin/expired: `preview_mapping_expired`, yêu cầu preview mới.
- Title/company/job URL thiếu: preview fail; location có thể absent explicit.
- Pagination lặp URL, detail trùng identity hoặc vượt budget: run `partial/incomplete`; không removal.
- Layout drift: complete coverage bị hạ `incomplete`, recipe `blocked` sau bounded failure gate và cần
  preview/mapping mới.
- CAPTCHA/auth/paywall/access denial: `blocked`, không retry/bypass.
- Malformed JSON-LD/HTML: fallback deterministic; nếu không đủ thì safe preview failure.
- Crash/timeout: transaction rollback; canonical current state không bị xóa.
- Empty run chỉ là completeness signal khi recipe đã có complete baseline và empty-anomaly gate pass;
  nếu không thì `incomplete`.

## Testing và acceptance

### Unit/contract

- terms notice/acknowledgement version, exact-origin binding và owner isolation;
- HTTPS, user-info, custom port, DNS/IP, redirect/path/host boundary negatives;
- structured data, heuristic và saved mapping fixtures;
- opaque element ID origin/expiry/tamper tests;
- seniority VI/EN aliases, `all`, multi-select và unknown filtering;
- schedule 6-hour/daily/weekly timezone/DST/idempotency;
- challenge/auth/paywall/429/5xx error taxonomy;
- API/OpenAPI/BFF request allow-list và screenshot size contract.

### PostgreSQL/integration

- destructive migration purge đúng source-derived graph và giữ auth/operator/resume/rule data;
- migration failure rollback, no partial purge;
- create → acknowledge → preview → mapping correction → enable → manual/scheduled run;
- same input rerun idempotent;
- failed/partial/layout-drift run không tạo false missing/removal;
- two qualified complete absences mới tạo missing/removed, rồi reactivation giữ history;
- recipe/source provenance và source-scoped identity;
- duplicate scheduler/API trigger không double processing.

### Browser/UI

- URL + seniority form ở desktop/mobile, VI/EN và keyboard accessible;
- terms warning rõ nhưng owner có thể continue;
- known restricted source preview được sau acknowledgement;
- screenshot mapper chọn card/field/pagination mà không lộ selector;
- enable chỉ sau preview 3–5 job;
- blocked source hiển thị reason và không có bypass action;
- Crawl now, schedule, polling/history và one-click startup smoke.

### Bắt buộc negative scenarios

1. URL private/metadata/redirect escape.
2. Source có restricted terms nhưng chưa acknowledgement.
3. Restricted terms đã acknowledgement và public page preview thành công.
4. CAPTCHA, login, paywall, anti-bot hoặc `403` vẫn bị chặn.
5. Malicious HTML/JS, prompt injection text, oversized response/screenshot.
6. Mapping nhầm/expired hoặc pagination loop.
7. Crawl lặp lại và duplicate trigger.
8. Crawl fail/partial/empty anomaly không false removal.
9. Seniority unknown không lọt vào filtered recipe.
10. Purge không đụng auth/operator/ResumeProfile ngoài JobMatch liên quan.

## Delivery slices

Một implementation plan bao phủ cùng design nhưng chia checkpoint độc lập:

1. ADR/domain/API/migration contract và destructive reset.
2. Xóa old systems, tạo `SourceRecipe`/preview queue và generic HTTP extraction.
3. Browser preview, screenshot mapper và pagination/detail traversal.
4. Scheduler, seniority filter, UI/BFF và ten-source catalog acceptance.
5. One-click launcher, docs/evidence, PostgreSQL/Compose/browser/full gates.

Không thêm Redis, Prefect, external AI, microservice, proxy service hoặc source-specific adapter. Direct
PostgreSQL queue, existing modular monolith và crawler container là đủ cho single-operator workload.

## Trade-offs được chấp nhận

- Owner có thể crawl public pages dù terms notice hạn chế; rủi ro block IP, takedown, yêu cầu xóa dữ
  liệu hoặc tranh chấp thuộc quyết định của owner và phải luôn được hiển thị trung thực.
- Không bypass nghĩa là một số source trong catalog sẽ vẫn `blocked/unavailable` về kỹ thuật.
- Generic recipe + visual correction giảm nhu cầu code nhưng không bảo đảm mọi website; interaction
  ngoài contract được báo `unsupported_interaction` thay vì thêm scripting language cho user.
- Purge sớm làm dashboard trống và mất dataset/evaluation hiện tại; no-backup làm mất dữ liệu không
  thể phục hồi. Đây là lựa chọn có chủ đích để tránh duy trì hai ingestion systems.
- Screenshot trong PostgreSQL phù hợp local single-operator nhưng không phải thiết kế scale-out; TTL và
  size cap giữ chi phí bounded.
