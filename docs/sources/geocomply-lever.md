# Source approval record: GeoComply on Lever

**Source key:** `geocomply-lever`

**Review date:** 2026-08-21

**Approval status:** `candidate`

**Policy status:** `permission_required`

**Operator decision:** `permission_required` — 2026-08-21

## 1. Decision summary

GeoComply's Lever board đạt technical gate: public JSON list/detail, posting UUID ổn định, country code `VN`, không cần credential/browser và Lever công bố rõ Postings API dành cho public job site. Robots của cả hosted site và API cho phép truy cập, với `Crawl-delay: 1`.

Source không được chuyển sang `approved`. Lever ghi published postings có thể bị third party scrape và hosted robots cho phép search/reference, nhưng employer vẫn sở hữu nội dung. GeoComply Website Terms cấm automated retrieval trên `www.geocomply.com`; operator quyết định giữ source ở `permission_required` thay vì dựa vào khác biệt host để mở trust boundary.

## 2. Proposed registry record

Đây là candidate configuration để review, chưa phải config chạy được:

```yaml
name: GeoComply Careers via Lever
source_key: geocomply-lever
approval_status: candidate
base_url: https://api.lever.co/v0/postings/geocomply-2
allowed_hosts:
  - api.lever.co
reference_hosts:
  - jobs.lever.co
adapter_key: lever_postings
adapter_scope:
  site: geocomply-2
discovery_mode: public_json_api
identity_strategy: external_id
external_id_field: id
expected_pagination: skip_limit_until_short_page
scope:
  countries:
    - VN
rate_limit:
  requests_per_minute: 10
  concurrency: 1
  timeout_seconds: 20
  redirect_limit: 3
  max_response_bytes: 2000000
user_agent: DevRadar/0.1 (+https://github.com/HPhucTV/DevRadar)
policy_review:
  status: permission_required
  robots_reviewed_at: 2026-08-21
  terms_reviewed_at: 2026-08-21
  next_review_at: 2026-11-21
```

`jobs.lever.co` là reference host cho `hostedUrl`, không phải fetch host của normal run. `www.geocomply.com` không thuộc allow-list. Link về employer chỉ được trả như external reference do source cung cấp, không được crawler follow.

## 3. Policy và public-access evidence

| Check | Evidence | Kết quả |
|---|---|---|
| Public board/API | [GeoComply board](https://jobs.lever.co/geocomply-2), [JSON list](https://api.lever.co/v0/postings/geocomply-2?mode=json) | HTTP 200, không login/API key/CAPTCHA trong bounded spike. |
| API intent | [Lever Postings API docs](https://github.com/lever/postings-api) | API dùng để dựng job site; published postings public và docs lưu ý có thể được third party scrape. |
| Robots | [hosted robots](https://jobs.lever.co/robots.txt), [API robots](https://api.lever.co/robots.txt) | `Allow: /`, `Crawl-delay: 1`; hosted signal `search=yes`, `ai-train=no`, `use=reference`. |
| Employer terms | [GeoComply Website Terms](https://www.geocomply.com/terms-of-service/) | Terms định nghĩa Site là `www.geocomply.com` và cấm scrape/systematic download trên Site. Domain này không được crawl. Terms không cấp rõ license cho employer-authored content trên Lever. |
| Privacy | [Applicant privacy notice](https://www.geocomply.com/applicant-privacy-notice/) | Chỉ liên quan application data; DevRadar không gọi application endpoint hoặc thu candidate data. |
| Contact/takedown | [GeoComply contact](https://www.geocomply.com/contact), Website Terms | `legal@geocomply.com` cho copyright/legal; operator phải pause source ngay khi có yêu cầu. |

Review này là engineering gate, không phải tư vấn pháp lý. Content signals cho search/reference không được diễn giải thành quyền AI training hoặc full-content public syndication.

## 4. Technical evidence

Bounded spike ngày 2026-08-21 với User-Agent đã khai báo:

| Request | Status | Response bytes | Observation |
|---|---:|---:|---|
| `GET .../geocomply-2?mode=json&limit=100` | 200 | 274,208 | 11 postings, 8 postings có `country=VN`/Vietnam location |
| một posting detail GET | 200 | 24,435 | UUID `1bb53e99-a9e6-4608-9a8d-2be79846eaee`, `country=VN` |

Các số liệu chỉ chứng minh shape tại thời điểm review, không phải baseline production.

### List/detail boundary

- Discover bằng `GET /v0/postings/geocomply-2?mode=json&skip=<n>&limit=100`.
- Chỉ chấp nhận site namespace literal `geocomply-2`; request không nhận site/user URL tùy ý.
- ListingRef gồm `id`, `hostedUrl`, title, country/location, team/department và workplace type raw.
- Detail chỉ được fetch bằng `id` đã xuất hiện trong list cùng run; không gọi `POST` application endpoint.
- `applyUrl` chỉ là outbound link cho user và không bao giờ được crawler follow hoặc submit.

### Identity

- Primary identity: `(source_id, Lever posting id)`.
- `id` là unique posting ID theo Lever docs; `hostedUrl` là canonical provenance.
- Thiếu/trùng UUID khác nội dung làm run `partial`; không fallback sang title/company hash.
- Nếu employer repost cùng role với UUID mới, đó là Job mới; cross-post similarity chỉ tạo candidate review ở phase sau.

### Run completeness

Lever list API không trả total count. Run chỉ có `coverage_status=complete` khi:

1. mọi batch `skip=0,100,...` trả JSON hợp lệ và tối đa 100 item;
2. tiếp tục cho tới batch cuối có ít hơn 100 item;
3. union UUID không có conflict; duplicate cùng payload được đếm/anomaly nhưng không tạo Job mới;
4. mọi URL trả về nằm trên `jobs.lever.co` và site path `geocomply-2`;
5. filter Việt Nam dùng `country == "VN"`; location text chỉ là evidence/fallback khi country null và phải review.

Batch lỗi, response đúng 100 item nhưng không fetch được batch kế, schema đổi hoặc response rỗng bất thường đều làm run `partial/incomplete`. V1 không kích hoạt missing/removal.

## 5. Extraction và data handling

- JSON API là deterministic source; không browser và không LLM trong V1.
- Ưu tiên plaintext fields (`descriptionPlain`, `openingPlain`, `additionalPlain`); HTML chỉ giữ trong raw snapshot và sanitize nếu cần canonical text.
- Chỉ ingest published posting data; không gọi application fields, không gửi CV và không lưu applicant consent/question data.
- `country`, categories, workplace type và salary range giữ raw/provenance trước normalization.
- V1 API local/private có thể trả sanitized description. Nếu public exposure được mở sau này, phải review lại content terms; mặc định chỉ title, company, location, source link và bounded excerpt.
- `ai-train=no`: raw/canonical content từ source này không được dùng để train/fine-tune model. LLM extraction V3 cần policy review mới, không kế thừa approval V1.

## 6. Failure, throttle và source health

- Concurrency 1, tối đa 10 request/phút; luôn chậm hơn `Crawl-delay: 1`.
- Tôn trọng `Retry-After`; không đổi host/User-Agent hoặc browser để vượt 403/429/challenge.
- Redirect ra ngoài `api.lever.co` bị block; `hostedUrl` trên reference host không được crawler follow.
- Response ngoài JSON/HTML đã duyệt hoặc body vượt 2 MB bị policy-blocked.
- UUID conflict, country field biến mất hàng loạt, count giảm bất thường hoặc schema đổi làm source degraded/quarantined; không suy ra removed.
- Robots, Lever docs hoặc employer terms thay đổi làm source pause cho tới re-review.

## 7. Fixture và smoke plan

Fixture cần capture sau khi operator approve, đã loại tracking/PII không cần thiết:

- list JSON có nhiều Vietnam/non-Vietnam postings;
- detail happy path với plaintext và HTML fields;
- optional salary/workplace type null;
- missing/invalid `country` và location fallback;
- malformed JSON/schema;
- duplicate UUID conflict;
- short final page và exact-limit page;
- 429/timeout và redirect ngoài allow-list.

Live smoke tối đa một list page và một detail; không gọi application endpoint và không chạy schedule trước khi fixture tests pass.

## 8. Approval checklist

| Gate | Status |
|---|---|
| Public, no auth/bypass | Pass |
| Robots reviewed | Pass |
| Stable identity | Pass |
| List/detail và completeness strategy | Pass |
| Rate/timeout/redirect/size limits | Pass as conservative proposal |
| Vietnam IT scope | Pass |
| Browser unnecessary | Pass |
| Contact/takedown | Pass |
| Lever/employer content-use scope | **Permission required** |
| Operator approval | Not approved — user decision ngày 2026-08-21 |

## 9. Điều kiện xem xét lại

Source chỉ được xem xét chuyển `approved` khi có written permission hoặc policy mới cho phép automated retrieval/storage trong phạm vi DevRadar. Lever API availability, robots hoặc khác biệt domain không tự mở khóa quyết định này.

Cho tới lúc đó, source không được thêm vào active registry và không được crawl ngoài bounded policy evidence đã thực hiện ngày review.
