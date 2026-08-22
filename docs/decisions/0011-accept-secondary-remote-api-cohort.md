# ADR-011: Chấp nhận cohort remote thứ cấp cho V3 scale gate

## Status

Accepted cho V3 local/private non-commercial scope.

## Date

2026-08-22

## Context

V3-006 cần tối thiểu 500 canonical Job từ approved/reproducible runs. Ba source Việt Nam hiện có chỉ cho `78` Job (`14 + 27 + 37`), thiếu `422`. Các candidate Vietnam khác đang giữ `permission_required` hoặc bị loại bởi terms/anti-bot; không được crawl để lấp gap bằng cách suy đoán quyền.

RemoteJobs.org công bố một public JSON API dành cho việc nhúng job vào “site, app, or tool”, không cần signup/API key, giới hạn tối đa 50 item/request và pagination `limit/offset`. Trang API ghi API free/open với reasonable use, cập nhật hằng ngày từ 5 nguồn và yêu cầu attribution “Powered by RemoteJobs.org” khi hiển thị. Bounded request ngày 2026-08-22 với category `programming&limit=1` trả HTTP 200, `pagination.total=1001`, UUID `id`, canonical `url` trên `remotejobs.org` và full description.

Đây là nguồn remote toàn cầu, không phải bằng chứng cho thị trường Việt Nam. Nếu đưa vào cùng cohort mặc định mà không gắn nhãn, analytics sẽ dễ overclaim. Cần một boundary dữ liệu riêng và không được tự quy đổi currency/multi-country location ở V3.

## Decision

- Chấp nhận source key `remotejobs-org` cho **secondary global-remote IT cohort** trong local/private non-commercial V3 scope.
- Chỉ dùng public GET API `https://remotejobs.org/api/v1/jobs`; không crawl HTML, sitemap, company pages hoặc external `apply_url`.
- Chỉ cho phép category slug cố định trong registry: `programming`, `data-science`, `devops`, `product-management`, `design`; request không nhận URL/filter tùy ý.
- Identity là API UUID `id`; canonical provenance URL là `url` phải ở host `remotejobs.org`. Không dùng title/company hash thay UUID.
- Paginate bằng `limit <= 50`, `offset` tăng tới `pagination.has_more=false`; `pagination.total` và duplicate/conflict checks là completeness invariant. Terminal page được chấp nhận khi `offset + item_count >= total` vì API đã quan sát overrun (`offset=1000,total=1001,count=50,has_more=false`); underrun (`< total`), batch/schema lỗi hoặc UUID/URL conflict làm run `incomplete`, không phát `missing/removed`.
- Áp rate bảo thủ hơn quyền công bố: concurrency `1`, tối đa `2 requests/minute` (30 giây giữa request), timeout `20s`, response tối đa `2 MiB`. Retry chỉ transient và bounded. Mức `6/minute` ban đầu bị API trả `429` trong live smoke và đã bị loại bởi evidence.
- Giữ raw salary/location/language/description và provenance; không quy đổi currency, không suy ra Việt Nam từ text, không trộn mặc định với Vietnam-market claim.
- Source attribution phải được lưu trong `Source`/provenance và UI public tương lai phải hiển thị “Powered by RemoteJobs.org” cùng link về posting/source. Nếu operator nhận takedown hoặc API policy đổi, pause source ngay.
- Source được phép vào active registry sau khi approval record và fixtures/adapter contract tồn tại; không dùng source này để thay đổi `V1` approved Vietnam allow-list hoặc mở V4.

## Alternatives considered

### Chỉ mở rộng thêm employer ATS tại Việt Nam

Không đủ evidence hiện tại. Greenhouse/Lever technical API không tự cấp quyền employer-content; KMS/Trusting Social terms hạn chế automated retrieval/republication và GeoComply/Lever vẫn `permission_required`.

### Arbeitnow hoặc Remotive

Chưa chấp nhận. Arbeitnow terms giới hạn copy/public display dù API có link-back; Remotive API page cho phép share có attribution nhưng Terms of Use hiện cấm automated access/republication rộng hơn. Cần policy clarification/written permission riêng trước khi active.

### Crawl RemoteJobs.org HTML để lấy nhiều hơn API

Rejected. API đã cung cấp inventory đủ lớn, HTML/sitemap không cần thiết và mở rộng trust boundary không có lợi ích đo được.

## Consequences

### Positive

- Có một nguồn API minh bạch, volume đủ để đóng gap `>=500` nếu complete run giữ được inventory.
- UUID/pagination/schema rõ, không cần browser hoặc dependency mới.
- Cohort remote riêng giúp semantic/evaluation có dữ liệu đa dạng nhưng vẫn tránh tuyên bố sai về Việt Nam.

### Trade-offs

- Dữ liệu global remote làm currency/location heterogeneous; V3 chỉ giữ raw và phải lọc cohort khi demo.
- Inventory là aggregated feed từ 5 nguồn, không phải employer-source provenance đầy đủ; `Source` phải ghi `remotejobs.org` là upstream và không suy diễn employer license.
- Attribution và takedown boundary trở thành acceptance condition cho public display.

## Official-source basis

- RemoteJobs.org API access and terms: <https://remotejobs.org/api-access>
- RemoteJobs.org robots: <https://remotejobs.org/robots.txt>
- RemoteJobs.org about/source identity: <https://remotejobs.org/about>

## Acceptance gate

- Approval record ghi rõ API-only scope, policy evidence, attribution, takedown và rate limit.
- Fixture list/detail schema, malformed/duplicate/total mismatch và pagination-complete tests pass.
- Active registry chỉ thêm `remotejobs-org` sau khi adapter contract và allow-list code đã review.
- Bounded live smoke phải chứng minh API response, UUID uniqueness, completeness và no false removal; failed/partial runs không đóng inventory gate.
