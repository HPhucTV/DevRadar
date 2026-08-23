# DevRadar Custom Source Profile Design

## Mục tiêu

Cho phép single-operator khai báo một website tuyển dụng riêng trên giao diện web, chạy crawl theo lịch và đưa dữ liệu hợp lệ vào ingestion pipeline hiện tại mà không làm suy yếu source policy, SSRF protection hoặc quyền truy cập.

Custom source là profile `local/protected` do owner tạo. Nó không trở thành source public/approved toàn hệ thống và không được bật khi deployment không phải local/protected.

## Quyết định đã chốt

- User nhập `baseUrl` và cấu hình lịch crawl trong web UI.
- Một profile phải qua `preview` thành công trước khi schedule được enable.
- Parser dùng hybrid deterministic:
  1. JSON/API hoặc JSON-LD;
  2. HTML semantic selectors;
  3. selector/JSON-path mapping do owner chỉnh trong profile nếu auto-detection chưa đủ.
- Browser rendering chỉ là fallback được bật rõ ràng cho profile; không dùng persistent browser profile và không bypass access control.
- Crawl custom chỉ chạy qua authenticated owner/operator flow và same-origin BFF; không nhận URL tùy ý trong public API hoặc mỗi lần run.
- Source status riêng là `owner_authorized_local`, `paused`, `blocked` hoặc `retired`; không tái sử dụng `approved` để che khác biệt policy.
- Khi gặp `401`, `403`, CAPTCHA, paywall, anti-bot challenge hoặc redirect ngoài boundary, run dừng fail-closed, profile chuyển `blocked` với `blockReason=permission_required` hoặc policy error và không tự retry.
- User phải chịu trách nhiệm xác nhận quyền truy cập/khai thác source; checkbox không biến một source không được phép thành hợp pháp.
- Vẫn giữ HTTPS-only, DNS/private-IP blocking, redirect revalidation, response/page/time budget, rate limit và provenance.

## Không nằm trong phạm vi

- CAPTCHA solving hoặc CAPTCHA-solving service.
- Bypass authentication, paywall, robots/anti-bot hoặc access control.
- Nhận proxy URL công khai để fetch hộ arbitrary destination.
- Lưu credential, cookie, browser profile hoặc token của website trong V1 custom profile.
- Public custom-source onboarding, multi-tenant sharing hoặc anonymous crawl.
- Tự động merge cross-source hoặc dùng custom source để claim thị trường Việt Nam khi chưa có cohort evidence.

## Trải nghiệm người dùng

### Tạo profile

Owner mở `Sources → Add custom source` và nhập:

- tên source;
- base URL (HTTPS, không có user-info/custom port/fragment);
- path prefix được phép, mặc định là path của base URL;
- parser mode: `auto`, `html` hoặc `json`;
- optional field mapping cho `title`, `company`, `location`, `salary`, `description`, `postedAt`, `externalId` và `jobUrl`;
- crawl budget: page limit, item limit, response byte limit và rate limit;
- lịch `interval` hoặc `daily_at` cùng timezone IANA;
- xác nhận owner có quyền sử dụng source trong local/protected deployment.

### Preview trước khi bật lịch

`Test crawl` chạy một bounded preview không ghi canonical `Job`. Kết quả hiển thị:

- final URL và redirect chain đã được kiểm tra;
- parser mode/version;
- số item phát hiện;
- candidate fields và provenance selector/JSON path;
- warning về field thiếu, duplicate, coverage chưa biết hoặc challenge;
- safe error code nếu bị policy block.

Owner chỉ có thể `Enable schedule` khi preview có ít nhất một candidate hợp lệ và không có policy/challenge error. Preview không được trở thành removal signal.

### Vòng đời profile

```text
draft → preview_ready → enabled
enabled → degraded | blocked | paused
blocked → preview_ready (sau khi owner sửa config/quyền và chạy preview mới)
enabled → retired
```

`blocked` không được tự động quay lại `enabled`. `paused` dừng schedule nhưng giữ history. `retired` không nhận run mới và giữ provenance theo retention policy hiện hành.

## Kiến trúc và data flow

```text
Owner UI
  → authenticated BFF
  → CustomSourceProfile + schedule
  → direct PostgreSQL-backed scheduler
  → bounded custom adapter
  → SafeHttpFetcher / ephemeral browser fallback
  → RawJobSnapshot + parser candidates
  → deterministic validation/normalization
  → JobUpsert source-scoped identity
  → JobChange/source health/analytics
```

Custom adapter phải tái sử dụng `SafeHttpFetcher`, `RunContext`, snapshot persistence, normalization, deduplication, change detection và health workflow hiện tại. Adapter không được tự commit hoặc tự quyết định retry.

Mỗi custom `Job` phải truy ngược được tới custom profile, `Source`, `CrawlRun`, raw snapshot, final URL và parser version. Cross-source similarity chỉ tạo candidate; không auto-merge.

## Boundary URL và network

- `baseUrl` là input duy nhất để tạo source boundary; mỗi run chỉ được request host/path đã lưu trong profile.
- Chỉ HTTPS; reject localhost, IP literal, private, loopback, link-local, multicast, reserved và metadata ranges sau khi resolve tất cả DNS records.
- Mỗi redirect phải revalidate scheme, host, path và resolved addresses; không follow redirect ra ngoài profile boundary.
- Không nhận arbitrary headers, cookies, proxy, custom DNS hoặc credential từ browser.
- `browser` fallback dùng fresh ephemeral context, chặn download/popup/service worker/external protocol và giới hạn page/request/byte/time/memory budget.
- HTTP `401/403/429`, access challenge markers, CAPTCHA/paywall markers và repeated layout failure là policy/data stop, không phải transient retry.

## Schedule contract

- `interval`: số phút tối thiểu do policy đặt, không cho burst schedule;
- `daily_at`: `HH:mm` và IANA timezone, được chuyển sang UTC slot deterministically;
- mỗi profile chỉ có một active run;
- duplicate trigger key phải idempotent;
- scheduler, retry count, persistence và state transition là deterministic; không dùng agent để quyết định.

## API định hướng

Các endpoint mới chỉ được mở khi `DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED=true` và authenticated owner:

```text
GET    /api/v1/custom-sources
POST   /api/v1/custom-sources
GET    /api/v1/custom-sources/{profileId}
PATCH  /api/v1/custom-sources/{profileId}
DELETE /api/v1/custom-sources/{profileId}
POST   /api/v1/custom-sources/{profileId}/preview
POST   /api/v1/custom-sources/{profileId}/crawl-runs
```

Mutation không nhận URL tự do ngoài create/update profile. Response dùng JSON envelope/error contract hiện hành; list có pagination. API không trả raw HTML đầy đủ hoặc secret/cookie trong response. Thay đổi endpoint/schema/status phải cập nhật `docs/API.md`, OpenAPI contract và negative tests.

## Dữ liệu và quyền riêng tư

- Raw snapshot giữ provenance theo retention hiện hành và có owner-scoped deletion path.
- Log/metric chỉ ghi profile ID, source key, run ID, safe error code, counts và hash; không ghi raw HTML, full URL query có token, cookie hoặc credential.
- Nội dung custom source vẫn là untrusted input và không được thay đổi policy, tool allow-list hoặc quyền truy cập.
- Không gửi custom JD/CV tới external LLM theo privacy policy hiện hành.
- Source custom không được dùng làm public market claim nếu thiếu cohort/coverage evidence.

## Testing và acceptance

### Unit/contract

- URL boundary reject non-HTTPS, user-info, custom port, private/reserved DNS, path escape và redirect escape.
- Schedule chuyển timezone/DST deterministically, reject interval dưới policy minimum và duplicate trigger key.
- Auto parser nhận JSON-LD/HTML fixture; mapping override thắng auto-detection; malformed/empty/challenge fixture trả safe status.
- Preview không tạo `Job`, `missing`, `removed` hoặc `JobChange`.
- Source profile không thể chạy khi feature flag tắt hoặc session/owner không hợp lệ.

### Integration/browser

- Owner tạo profile → preview → enable → manual run → crawl history.
- Failed/partial/challenge run không làm false removal và chuyển đúng `blocked`/`degraded`.
- Rerun cùng input idempotent; source-scoped external ID/canonical URL không tạo duplicate.
- Public unauthenticated request, arbitrary URL field, cross-owner profile ID và unapproved transition đều bị từ chối.
- 401/403/429/CAPTCHA/paywall marker không được retry tự động.

## Trade-off

Thiết kế này cho phép owner theo dõi website riêng và tái sử dụng pipeline hiện tại, nhưng không biến DevRadar thành proxy crawler không giới hạn. Đổi lại, source phức tạp cần mapping/adapter và những website chặn automated access sẽ dừng ở `blocked` cho tới khi có quyền hoặc official integration.
