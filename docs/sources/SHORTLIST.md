# Shortlist nguồn job cho V1

**Ngày review:** 2026-08-21

**Phạm vi:** job IT công khai tại Việt Nam và cohort remote toàn cầu được gắn nhãn riêng cho V3 scale

**Trạng thái:** discovery mở rộng; approval outcome hiện tại là `4 approved`, `3 permission_required/hold` và `2 rejected_for_v1`

## 1. Kết luận

Ba source đã đạt approval gate cho local non-commercial spike:

1. **VNG Careers** — nguồn doanh nghiệp Việt Nam, HTML server-rendered có `job_id` ổn định;
2. **NAVER Vietnam trên Greenhouse** — public Job Board API, job post ID ổn định và dataset tập trung vào kỹ thuật tại Việt Nam;
3. **MoMo Careers** — SSR identity ổn định, fixed IT group và public UI load-more có completeness strategy qua browser.

V3 bổ sung một source thứ cấp cho cohort remote toàn cầu:

4. **RemoteJobs.org public API** — API JSON công khai, UUID/pagination rõ và volume programming đủ lớn cho scale gate; chỉ dùng API-only với attribution, không đại diện cho thị trường Việt Nam.

Mỗi source chỉ được dùng trong boundary của approval record riêng và phải đáp ứng [source approval gate](../INGESTION.md#2-source-approval-gate). `approved` ở đây không cấp license tái xuất bản, commercial reuse, public scheduled crawl hoặc AI training.

**GeoComply/Lever** đạt technical gate nhưng giữ `permission_required`: GeoComply Website Terms cấm automated retrieval và operator không dùng khác biệt host để nới trust boundary. Các source cần bypass anti-bot, credential, hoặc có điều khoản hạn chế retrieval/republication tiếp tục không được duyệt.

## 2. Phương pháp review

- Chỉ đọc trang tuyển dụng, policy, robots và tài liệu API công khai; không đăng nhập, submit form, tạo account hoặc bypass control.
- Mỗi số lượng job là một bounded observation tại ngày review, không phải cam kết về coverage lâu dài.
- Không crawl list/detail hàng loạt. Technical identity chỉ được xác minh bằng một list response và tối đa một detail response khi cần.
- `robots.txt` là một policy signal, không thay thế terms, copyright hoặc approval của operator.
- Review này là engineering gate cho portfolio, không phải tư vấn pháp lý.

## 3. Shortlist và disposition

| Candidate | Public scope và identity | Extraction / JS | Robots review | Terms / policy review | Disposition |
|---|---|---|---|---|---|
| **VNG Careers** | List/detail công khai, không cần login. Bounded list response có `job_id`, `slug`, 86 job và 9 page; nhóm Software, Data Engineering, Data Science và AI có mặt. Detail URL chứa `job_id` và slug. | Next.js nhưng list và detail có dữ liệu trong server-rendered `__NEXT_DATA__`; HTTP-first đủ cho spike, chưa có lý do dùng browser. | 2026-08-21: HTTP 200, `User-agent: *`, `Allow: /`, có sitemap. | Chưa tìm thấy content-use terms riêng. Operator duyệt bounded local non-commercial scope với contact/takedown và re-review gate. | `approved_local_noncommercial_spike`; xem [approval record](vng-careers.md). |
| **GeoComply / Lever** | Board và JSON API công khai. Một bounded list request thấy 11 posting, trong đó 8 tại Thành phố Hồ Chí Minh; `id` là posting UUID và `hostedUrl` là detail identity. | Public JSON list/detail; không cần browser. Chỉ dùng GET posting data, không dùng application endpoint. | 2026-08-21: `jobs.lever.co` và `api.lever.co` đều HTTP 200, `Allow: /`, `Crawl-delay: 1`; hosted site ghi `search=yes`, `ai-train=no`, `use=reference`. | Lever docs nói published postings là public, API dùng để dựng job site và postings có thể được third party scrape. GeoComply Website Terms cấm automated retrieval; operator giữ boundary ở `permission_required`. | `permission_required`; không chọn cho V1 nếu chưa có written permission/policy mới. |
| **NAVER Vietnam / Greenhouse** | Board và JSON API công khai. Một bounded list request thấy 14/14 job ở Việt Nam; mỗi posting có numeric `id`, `absolute_url` và `meta.total` cho coverage. | Public JSON list/detail; không cần browser. | 2026-08-21: job board HTTP 200 không có `Disallow`; API robots HTTP 200 chỉ disallow `/embed/`, không chặn `/v1/boards/...`. | Greenhouse docs ghi GET Job Board data công khai, không cần authentication và dành cho custom career site. Operator duyệt bounded local non-commercial scope; employer content license vẫn không được suy diễn. | `approved_local_noncommercial_spike`; xem [approval record](naver-vietnam-greenhouse.md). |
| **MoMo Careers** | Filter `DGM.0001` trả 37 job IT; SSR có `TotalItems/PageCount` và stable `jobId/jobCode/subdirectory`. | SSR chỉ có batch đầu; public `Xem thêm` tăng 12 → 24 item. Browser cần thiết cho pagination, direct API replay bị cấm. | 2026-08-21: career/API-host robots đều HTTP 404, không có directive cấm; absence không phải permission. | Không tìm thấy career content-use terms. Operator duyệt bounded local non-commercial scope, exact allow-list và re-review khi policy/control đổi. | `approved_local_noncommercial_spike`; xem [approval record](momo-careers.md). |
| **RemoteJobs.org public API** | API JSON `GET /api/v1/jobs`, UUID `id`, canonical `url`, category filter và `pagination.total/has_more`; bounded `programming` observation `1001` jobs. | HTTP/API-first, không cần browser/detail; không fetch HTML/company/apply URL. | 2026-08-22: `robots.txt` HTTP 200, `Allow: /`; chỉ disallow `/admin` và `/knicks-2026`. | API page cho phép embed trong site/app/tool, free/open/no key, yêu cầu attribution; local/private non-commercial cohort remote toàn cầu, không claim Vietnam. | `approved_local_noncommercial_spike` cho V3 scale; xem [approval record](remotejobs-org.md). |
| **KMS Technology Careers** | List/detail công khai và có job IT Việt Nam; stable identity có thể lấy từ ATS/posting URL nhưng chưa spike. | HTTP/ATS path có thể dùng, browser chưa được chứng minh cần. | 2026-08-21: HTTP 200; không thấy disallow job path trong robots response. | Terms cho phép personal/informational non-commercial use nhưng hạn chế reproduce, publish và distribute khi chưa có written permission. DevRadar dự kiến lưu và hiển thị JD. | `permission_required`; không chọn cho V1 mặc định. |
| **Trusting Social Careers** | Career list công khai, có vị trí kỹ thuật tại Hà Nội/Thành phố Hồ Chí Minh; detail URL dùng numeric identity. | Nội dung list server-rendered; chưa cần browser cho discovery. | 2026-08-21: `/robots.txt` trả HTTP 404 page. | Policy Terms giới hạn download ở personal use và cấm copy, redistribution, retransmission hoặc publication nếu thiếu express permission. | `permission_required`; không chọn cho V1 mặc định. |
| **FPT Software Careers** | Có career site Việt Nam, nhưng request công khai tới robots bị Cloudflare challenge. | Không đánh giá tiếp vì access gate đã fail; không dùng browser để vượt challenge. | 2026-08-21: HTTP 403, trang “Just a moment...” với Cloudflare challenge. | Có privacy page, nhưng không làm thay đổi anti-bot blocker. | `rejected_for_v1`; review lại nếu public access thay đổi. |
| **Endava / SmartRecruiters** | Employer có job Việt Nam và Posting API có posting `id`/`uuid`. | API kỹ thuật phù hợp nhưng docs hiện ghi API key authentication; không đưa credential tương lai vào V1. | 2026-08-21: `api.smartrecruiters.com/robots.txt` disallow `/` cho `User-agent: *`; career host robots trả 404 page. | Endava có recruitment privacy notice. Policy/API boundary hiện không phù hợp source public không credential. | `rejected_for_v1_api`; public HTML chỉ được xét lại bằng approval task mới. |

## 4. Evidence chính

### VNG Careers

- [Job list](https://career.vng.com.vn/tim-kiem-viec-lam)
- [Sample detail](https://career.vng.com.vn/tim-kiem-viec-lam/chi-tiet/6849-senior-software-engineer-ai-inference-greennode-vi)
- [robots.txt](https://career.vng.com.vn/robots.txt)
- [Recruitment privacy policy](https://career.vng.com.vn/privacy-policy)

Bounded observation: list response trả HTTP 200 và chứa 10 job ở page 1, `total=86`, `pages=9`; sample detail trả HTTP 200. Các con số có thể thay đổi trước source approval.

### GeoComply trên Lever

- [GeoComply job board](https://jobs.lever.co/geocomply-2)
- [Lever public list endpoint](https://api.lever.co/v0/postings/geocomply-2?mode=json)
- [Lever Postings API documentation](https://github.com/lever/postings-api)
- [Hosted-site robots.txt](https://jobs.lever.co/robots.txt)
- [API robots.txt](https://api.lever.co/robots.txt)
- [GeoComply careers](https://www.geocomply.com/careers/all-jobs/)
- [GeoComply applicant privacy notice](https://www.geocomply.com/applicant-privacy-notice/)

Bounded observation: một JSON list request trả 11 posting, 8 posting có location `Ho Chi Minh, Vietnam`. Approval record phải chốt cách xác định complete run, filter Việt Nam và rate thấp hơn hoặc bằng policy công bố.

### NAVER Vietnam trên Greenhouse

- [NAVER Vietnam job board](https://job-boards.greenhouse.io/navervietnam)
- [Greenhouse public list endpoint](https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs)
- [Greenhouse Job Board API documentation](https://developer.greenhouse.io/job-board.html)
- [Job-board robots.txt](https://job-boards.greenhouse.io/robots.txt)
- [API robots.txt](https://boards-api.greenhouse.io/robots.txt)
- [NAVER Vietnam recruitment data policy](https://navercorp.vn/en/data_policy.html)

Bounded observation: một JSON list request trả `meta.total=14`; toàn bộ 14 posting có location tại Việt Nam. Approval record phải phân biệt `id` của job post với `internal_job_id` và chỉ dùng public GET endpoints.

### MoMo Careers

- [Job list](https://momo.careers/jobs-opening)
- [Filtered IT list](https://momo.careers/jobs-opening?groups=DGM.0001)
- [Sample detail](https://momo.careers/jobs/it-business-analyst-ii-17404)
- [robots.txt](https://momo.careers/robots.txt)
- [Approval record](momo-careers.md)

Bounded observation: filtered SSR response trả 37 job, 4 batch và 12 item đầu; một public UI `Xem thêm` tăng số job link lên 24. Browser được dùng theo UI công khai, không tái tạo request token hoặc gọi API nền trực tiếp.

### RemoteJobs.org public API

- [API access and usage](https://remotejobs.org/api-access)
- [robots.txt](https://remotejobs.org/robots.txt)
- [About/source identity](https://remotejobs.org/about)

Bounded observation ngày 2026-08-22: API `programming&limit=1` trả HTTP 200, `pagination.total=1001`, `has_more=true`, UUID `id`, canonical `url` trên `remotejobs.org` và description dài 2.205 ký tự. API page ghi free/open/no signup/API key, max 50 item/request, reasonable use và attribution “Powered by RemoteJobs.org”. Đây là remote/global cohort, không dùng để claim Vietnam.

### Candidate bị hold hoặc loại

- KMS Technology: [job list](https://careers.kms-technology.com/job/), [robots.txt](https://careers.kms-technology.com/robots.txt), [terms](https://kms-technology.com/terms-conditions/)
- Trusting Social: [careers](https://trustingsocial.com/careers/), [robots.txt](https://trustingsocial.com/robots.txt), [policy terms](https://trustingsocial.com/policy-terms/)
- FPT Software: [careers](https://career.fpt-software.com/), [robots.txt](https://career.fpt-software.com/robots.txt), [privacy](https://career.fpt-software.com/privacy/)
- SmartRecruiters/Endava: [Posting API](https://developers.smartrecruiters.com/docs/posting-api), [endpoints](https://developers.smartrecruiters.com/docs/endpoints), [API robots.txt](https://api.smartrecruiters.com/robots.txt), [Endava Vietnam careers](https://www.endava.com/careers/early-careers/internship-programmes/vietnam), [Endava privacy notice](https://www.endava.com/privacy-notice)

## 5. Approval task briefs

### PRE-004 — `vng-careers`

- Candidate hosts: `career.vng.com.vn`; không allow-list CDN vì SSR response đã chứa dữ liệu cần thiết.
- Proposed discovery: paginated HTTP list; parse server-rendered payload hoặc HTML fixture, không gọi private endpoint đoán từ bundle.
- Proposed identity: `job_id`; canonical URL là fallback và phải giữ slug thay đổi như observation.
- Approval record đã khóa content-use boundary, contact/takedown, pagination completeness, rate limit và fixture plan.

### PRE-005 — `geocomply-lever` (`permission_required`)

- Candidate fetch host: `api.lever.co`; `jobs.lever.co` chỉ là reference host; site namespace cố định `geocomply-2`.
- Proposed discovery: public JSON GET list; detail GET theo posting UUID khi list content không đủ contract.
- Proposed identity: Lever posting `id`; không gọi POST application endpoint và không thu candidate data.
- Blocker: written permission hoặc policy mới cho phép automated retrieval; technical readiness không override blocker.

### PRE-006 — `naver-vietnam-greenhouse`

- Candidate fetch host: `boards-api.greenhouse.io`; `job-boards.greenhouse.io` chỉ là reference host; board token cố định `navervietnam`.
- Proposed discovery: public JSON GET list/detail; không gọi application, Harvest hoặc internal endpoint.
- Proposed identity: public job post `id`; giữ `internal_job_id` chỉ như provenance nếu hiện diện, không dùng thay identity.
- Approval record đã khóa employer scope, `meta.total` completeness invariant, rate limit và fixture plan.

### PRE-005A — `momo-careers`

- Navigation host: `momo.careers`; browser network chỉ cho exact MoMo career request trên `aws.momo.vn`, không replay API trực tiếp.
- Discovery: `/jobs-opening?groups=DGM.0001`, parse SSR batch đầu rồi dùng public `Xem thêm` cho tới `TotalItems`.
- Identity: `jobId`; `jobCode/subdirectory` là cross-check và provenance.
- Browser bắt buộc vì HTTP query pagination bị ignore; mọi load-more/control failure làm run `incomplete`, không reverse-engineer token.
- Approval record đã khóa contact/takedown, rate/timeout/size, route allow-list, fixture và bounded live-smoke plan.

### PRE-V3-006A — `remotejobs-org`

- API host/path: `remotejobs.org/api/v1/jobs`; category chỉ lấy từ allow-list, không nhận URL tùy ý.
- Identity: UUID `id`; complete run dùng `pagination.has_more=false` cùng total/duplicate/schema checks.
- Cohort: `global_remote_it_secondary`; mọi demo phải hiển thị source/cohort và attribution “Powered by RemoteJobs.org”.
- Approval record đã khóa rate `2/minute` sau live `429` evidence, timeout/response size, no-follow `apply_url`, raw salary/currency preservation và takedown/pause boundary.

Ba source V1 tại Việt Nam được duyệt là VNG Careers, NAVER Vietnam/Greenhouse và MoMo Careers; RemoteJobs.org chỉ là source V3 thứ cấp cho remote cohort. GeoComply/Lever không thuộc V1 cho tới khi `permission_required` được giải quyết bằng evidence mới.
