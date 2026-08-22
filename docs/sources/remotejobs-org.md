# Source approval record: RemoteJobs.org public API

**Source key:** `remotejobs-org`

**Review date:** 2026-08-22

**Approval status:** `approved_local_noncommercial_spike`

**Cohort:** `global_remote_it_secondary`

**Operator decision:** approved cho local/private non-commercial V3 scale work; không phải approval cho commercial reuse, AI training hoặc claim thị trường Việt Nam.

## 1. Decision summary

RemoteJobs.org public API ghi rõ mục đích nhúng fresh remote job listings vào site/app/tool, không cần account/API key, JSON pagination và attribution. Bounded review request chỉ đọc category `programming`, không crawl HTML/company/apply URL.

Source này được duyệt như cohort remote toàn cầu thứ cấp để bổ sung scale cho V3. Vietnam sources vẫn là cohort ưu tiên; mọi analytics demo phải công bố source/cohort và không gọi remote inventory là thị trường Việt Nam.

## 2. Registry boundary

```yaml
name: RemoteJobs.org public API
source_key: remotejobs-org
approval_status: approved_local_noncommercial_spike
cohort: global_remote_it_secondary
base_url: https://remotejobs.org/api/v1/jobs
allowed_hosts:
  - remotejobs.org
reference_hosts:
  - remotejobs.org
adapter_key: remotejobs_api
adapter_scope:
  categories:
    - programming
    - data-science
    - devops
    - product-management
    - design
discovery_mode: public_json_api
identity_strategy: external_id
external_id_field: id
expected_pagination: limit_offset_until_has_more_false
rate_limit:
  requests_per_minute: 2
  concurrency: 1
  timeout_seconds: 20
  max_response_bytes: 2000000
policy_review:
  status: approved_local_noncommercial_spike
  robots_reviewed_at: 2026-08-22
  terms_reviewed_at: 2026-08-22
  attribution_required: true
  next_review_at: 2026-11-22
```

Config trên là approval boundary; caller chỉ được dùng source key/registry, không truyền URL hoặc category tùy ý.

## 3. Policy and public-access evidence

| Check | Evidence | Result |
|---|---|---|
| API purpose/permission | [API access page](https://remotejobs.org/api-access) | Trang chính thức nói có thể embed listings trong site/app/tool; free/open, no signup/API key. |
| Attribution | [API access page](https://remotejobs.org/api-access) | Yêu cầu hiển thị “Powered by RemoteJobs.org” khi hiển thị listing. DevRadar giữ requirement này cho public UI. |
| Rate/volume | [API access page](https://remotejobs.org/api-access) | `limit` tối đa 50; reasonable use/no hard cap; API công bố 800+ jobs và cập nhật hằng ngày từ 5 nguồn. Live `6/minute` bị `429`; DevRadar tự giới hạn `2/minute`. |
| Robots | [robots.txt](https://remotejobs.org/robots.txt) | HTTP 200; `Allow: /`, chỉ `Disallow: /admin` và `/knicks-2026`; API route không bị chặn. |
| Source identity | [About](https://remotejobs.org/about) | Domain/company identity và copyright notice của RemoteJobs.org; không có employer permission riêng được suy diễn. |
| Takedown/contact | API page | Trang hướng dẫn “Get in touch” khi cần higher limits/custom integration; operator phải pause và ghi nhận yêu cầu trước khi tiếp tục. |

Review là engineering gate, không phải legal opinion. Nếu API page/robots/terms đổi, source chuyển `paused` và cần re-review.

## 4. Bounded technical evidence

Ngày 2026-08-22, PowerShell `Invoke-WebRequest`/`Invoke-RestMethod` với khai báo User-Agent đã thực hiện:

```text
GET https://remotejobs.org/robots.txt
HTTP 200, 108 bytes

GET https://remotejobs.org/api/v1/jobs?category=programming&limit=1
HTTP 200, application/json, 3,160 bytes
pagination.total = 1001
pagination.limit = 1
pagination.has_more = true
data[0].id = 8320d0d0-6f30-4c38-81d7-149a2ddbe565
data[0].url host = remotejobs.org
data[0].category = programming
description length = 2205 characters
```

API response có `id`, `url`, `apply_url`, title/company/category/location/salary/type/description/posted_at và `meta.powered_by`. Run thật phải giữ `id`/URL provenance và không follow `apply_url`.

## 5. Completeness, identity and failure rules

- Discovery chỉ gửi exact API path với category nằm trong allow-list; `limit` tối đa 50 và `offset` tăng theo response.
- `pagination.total` phải ổn định trong run; `has_more=false` là terminator. API đã trả terminal overrun (`offset=1000,total=1001,count=50`), nên adapter chấp nhận `offset+count >= total` nhưng vẫn fail nếu underrun, JSON malformed, duplicate UUID conflict, missing URL hoặc host ngoài allow-list.
- UUID `id` là external identity. Cùng UUID khác content tạo anomaly/review, không tự merge.
- API outage/timeout/429 chỉ ghi run failure/partial; không chuyển Job thành `missing/removed`. Live smoke đầu tiên ở `6/minute` bị `429`; policy hiện hành hạ xuống `2/minute` và retry bounded.
- `url` và `apply_url` chỉ là provenance/outbound reference; crawler không mở external employer/apply host.
- Raw salary text, currency, location và translated/original-language fields giữ nguyên; V3 không quy đổi hoặc suy ra country/cohort ngoài source field.

## 6. Data handling and attribution

- Lưu source snapshot/provenance theo normal DevRadar pipeline; không dùng raw feed để train/fine-tune model.
- Search/analytics phải hỗ trợ filter source/cohort; dashboard tương lai hiển thị cohort `global_remote_it_secondary` và attribution “Powered by RemoteJobs.org”.
- Không public full-JD hoặc commercial syndication trước khi có review mới; local portfolio preview chỉ ở protected/private boundary.
- Khi có takedown/policy change, disable source key, giữ audit evidence cần thiết và đánh giá retention theo policy.

## 7. Open gates before active crawl

- Adapter fixture list, malformed response, duplicate/conflict, pagination total mismatch và empty-page tests.
- Registry config review và safe HTTP host/route negative tests.
- Một complete bounded live run đủ inventory với no false removal; `--max-items` không được dùng làm completeness evidence.
