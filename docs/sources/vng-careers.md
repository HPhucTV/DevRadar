# Source approval record: VNG Careers

**Source key:** `vng-careers`

**Review date:** 2026-08-21

**Approval status:** `approved`

**Operator decision:** `approved_local_noncommercial_spike` — 2026-08-21

## 1. Decision summary

VNG Careers đạt technical gate cho một HTTP-first adapter: list và detail công khai, không cần login, dữ liệu server-rendered có `job_id` ổn định, pagination có `total/pages`, robots cho phép truy cập và có contact tuyển dụng chính thức.

Career site không công bố content-use terms riêng; privacy policy chỉ điều chỉnh dữ liệu ứng viên. Operator đã review evidence và duyệt source chỉ cho local non-commercial spike/on-demand V1 ingestion, với rate/allow-list trong record này. Approval không cấp quyền public full JD, scheduled crawling ngoài local, commercial reuse hoặc AI training; các phạm vi đó phải re-review.

## 2. Approved registry record

Config chạy được nằm trong [V1 source registry](../../src/devradar/ingestion/source_registry.py). V1 pin thêm public `job_group` ID tương ứng cho từng family và revalidate cặp ID/name từ SSR taxonomy ở mỗi page:

```yaml
name: VNG Careers
source_key: vng-careers
approval_status: approved
base_url: https://career.vng.com.vn
allowed_hosts:
  - career.vng.com.vn
adapter_key: vng_careers
discovery_mode: server_rendered_html
identity_strategy: external_id
external_id_field: job_id
expected_pagination: numbered_pages_with_reported_total
scope:
  countries:
    - VN
  job_families:
    - Software
    - System
    - QC/P-QA
    - Tech Management
    - Data Engineering
    - Data Science
    - Business Analysis
    - Artificial Intelligence
  job_group_ids:
    - "385" # Software
    - "423" # System
    - "384" # QC/P-QA
    - "387" # Tech Management
    - "457" # Data Engineering
    - "462" # Data Science
    - "464" # Business Analysis
    - "465" # Artificial Intelligence
rate_limit:
  requests_per_minute: 6
  concurrency: 1
  timeout_seconds: 20
  redirect_limit: 3
  max_response_bytes: 2000000
user_agent: DevRadar/0.1 (+https://github.com/HPhucTV/DevRadar)
policy_review:
  status: approved_local_noncommercial_spike
  robots_reviewed_at: 2026-08-21
  terms_reviewed_at: 2026-08-21
  next_review_at: 2026-11-21
```

## 3. Policy và public-access evidence

| Check | Evidence | Kết quả |
|---|---|---|
| Public list/detail | [Job list](https://career.vng.com.vn/tim-kiem-viec-lam), [sample detail](https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/6852-social-marketing-collaborator-vi) | HTTP 200, không login/token/CAPTCHA trong bounded spike. |
| Robots | [robots.txt](https://career.vng.com.vn/robots.txt) | `User-agent: *`, `Allow: /`, có sitemap. |
| Terms | Footer và site search ngày 2026-08-21 | Chỉ thấy recruitment privacy policy; không tìm thấy content-use terms riêng. Đây là blocker, không được diễn giải im lặng thành permission. |
| Privacy | [Recruitment privacy policy](https://career.vng.com.vn/privacy-policy) | Điều chỉnh dữ liệu cá nhân của ứng viên; crawler không submit CV/form và không thu candidate data. |
| Contact/takedown | [VNG Careers home](https://career.vng.com.vn/vi) | `recruitment@vng.com.vn`, điện thoại `028 39223888`. Operator phải pause source ngay khi có yêu cầu. |

Review này là engineering gate, không phải tư vấn pháp lý. Việc robots cho phép không thay thế quyết định về lưu hoặc hiển thị nội dung.

## 4. Technical evidence

Bounded spike ngày 2026-08-21 với User-Agent đã khai báo:

| Request | Status | Response bytes | Observation |
|---|---:|---:|---|
| list page 1 | 200 | 129,855 | 10 items, `total=86`, `pages=9`, `request.page=1` |
| list page 2 | 200 | 150,459 | 10 items, cùng `total=86/pages=9`, `request.page=2` |
| một detail | 200 | 52,870 | URL chứa `job_id=6852`; page server-rendered |

Các số liệu chỉ chứng minh shape tại thời điểm review, không phải baseline production.

### List/detail boundary

- Discover từng group từ `/tim-kiem-viec-lam?job_group=<approved-id>&page=<n>`; response phải phản ánh exact filter trong `request.queries`.
- Parse JSON trong `<script id="__NEXT_DATA__" type="application/json">`; không đoán hoặc gọi private endpoint từ JavaScript bundle.
- ListingRef tối thiểu gồm `job_id`, `slug`, canonical detail URL, title, location, approved job group và broad `job_family` raw.
- Detail URL chỉ được tạo bằng `base_url` và `slug` từ listing payload.
- Không submit application/talent-community form và không fetch attachment.

### Identity

- Primary identity: `(source_id, job_id)`.
- Canonical URL là provenance/fallback, không phải primary identity vì slug có thể đổi khi title đổi.
- Nếu cùng `job_id` xuất hiện với slug mới, cập nhật URL observation; không tạo Job mới.
- Thiếu hoặc trùng `job_id` làm run `partial` và tạo parser error; không fallback sang title hash.

### Run completeness

Run chỉ có `coverage_status=complete` khi:

1. page 1 trả integer `total >= 0`, `pages >= 1` và `request.page=1`;
2. mọi page từ 1 đến `pages` trả thành công, page number khớp request và payload hợp lệ;
3. union theo `job_id` không có conflict và số item duy nhất bằng `total`;
4. `total/pages` không thay đổi giữa các page; nếu thay đổi, run là `incomplete` để tránh false absence;
5. từng page xác nhận public `tags` vẫn map approved job-group ID sang đúng name; broad `job_family` không quyết định scope;
6. mọi item từ server-confirmed approved group có detail URL hợp lệ; duplicate giữa groups chỉ merge khi identity/URL/title không conflict.

Response rỗng với `total > 0`, page giữa chuỗi lỗi, duplicate ID khác nội dung hoặc schema `__NEXT_DATA__` đổi đều làm run `partial/incomplete`. V1 không kích hoạt missing/removal dù run complete.

## 5. Extraction và data handling

- Dùng deterministic extraction từ SSR payload trước; HTML selector chỉ là fallback có fixture.
- Không dùng browser hoặc LLM trong V1.
- Chỉ lưu job posting; bỏ candidate form fields, tracking script, social widget và unrelated site content.
- Giữ `description`/`summary`, title, location, working type và job family raw trong snapshot; sanitize trước khi API render.
- Không ingest email/phone của cá nhân nếu vô tình xuất hiện trong JD; parser phải đánh dấu để review/redact theo policy dữ liệu.
- Public API V1 chạy local/private theo [API contract](../API.md); raw HTML không được trả user-facing.

## 6. Failure, throttle và source health

- Concurrency cố định 1; tối đa 6 request/phút trong V1 cho tới khi có evidence cho rate khác.
- Tôn trọng `Retry-After`; không quá ba attempt cho transient network/5xx trong future workflow V2.
- 401/403/429 lặp lại, CAPTCHA/challenge, robots hoặc terms thay đổi phải pause source; không đổi User-Agent hay browser để bypass.
- Detail redirect ra ngoài `career.vng.com.vn`, content type ngoài HTML hoặc body vượt 2 MB bị policy-blocked.
- `__NEXT_DATA__` biến mất, số item giảm bất thường hoặc page counters conflict làm source `degraded/quarantined`; không suy ra job removed.

## 7. Fixture và smoke evidence

Fixture đã capture/sanitize tại [VNG fixtures](../../tests/fixtures/vng), gồm:

- list page 1 và page cuối;
- detail job IT happy path;
- missing optional salary/level;
- malformed hoặc thiếu `__NEXT_DATA__`;
- duplicated `job_id` và slug thay đổi;
- empty result hợp lệ với `total=0`;
- pagination conflict và page timeout;
- redirect ngoài allow-list.

Fixture tests và bounded Software-group smoke hai list page + một detail đã pass; xem [V1-007 evidence](../evidence/V1-007-vng-adapter.md). Smoke dùng concurrency 1/6 request mỗi phút, không gọi private endpoint, browser, form hoặc schedule.

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
| Content-use terms phù hợp | Operator chấp nhận bounded local non-commercial scope; public/commercial use vẫn chưa được duyệt |
| Operator approval | Pass — user decision ngày 2026-08-21 |

## 9. Phạm vi approval

Operator decision ngày 2026-08-21 cho phép:

- bounded source/fixture spike và on-demand ingestion khi phát triển local V1;
- lưu raw snapshot/canonical data trong môi trường local, theo retention/security contract;
- chỉ fetch host/path/rate đã ghi trong record và pause/takedown tức thời.

Không được kế thừa approval này cho public full-JD exposure, schedule production, commercial reuse, external LLM hoặc AI training. Thay đổi terms/robots/control hoặc mở rộng phạm vi phải pause và re-review trước.
