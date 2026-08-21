# Source approval record: MoMo Careers

**Source key:** `momo-careers`

**Review date:** 2026-08-21

**Approval status:** `approved`

**Operator decision:** `approved_local_noncommercial_spike` — 2026-08-21

## 1. Decision summary

MoMo Careers đạt technical gate cho một browser-backed adapter có phạm vi hẹp: list/detail công khai, không cần login, filter chính thức cho `Trung tâm Công nghệ Thông tin`, SSR payload có `TotalItems/PageCount` và mỗi posting có `jobId`, `jobCode`, `subdirectory` ổn định. Luồng UI công khai tải batch tiếp theo bằng nút `Xem thêm` và đã tăng danh sách từ 12 lên 24 item trong bounded spike.

Career site không công bố `robots.txt` hoặc content-use terms riêng. Điều này không phải license. Operator chỉ duyệt local non-commercial spike/on-demand V1 ingestion theo boundary trong record này. Public full JD, scheduled/public crawling, commercial reuse, external LLM và AI training vẫn ngoài approval; policy/control mới phải làm source pause và re-review.

## 2. Proposed registry record

Đây là candidate configuration để review, chưa phải config chạy được:

```yaml
name: MoMo Careers
source_key: momo-careers
approval_status: approved
base_url: https://momo.careers
allowed_hosts:
  - momo.careers
browser_network_hosts:
  - aws.momo.vn
adapter_key: momo_careers
discovery_mode: browser_public_ui
identity_strategy: external_id
external_id_field: jobId
expected_pagination: public_load_more_until_reported_total
scope:
  countries:
    - VN
  division_group_id: DGM.0001
  division_group_name: Trung tâm Công nghệ Thông tin
rate_limit:
  page_concurrency: 1
  minimum_action_interval_seconds: 5
  timeout_seconds: 20
  redirect_limit: 3
  max_document_bytes: 2000000
user_agent: DevRadar/0.1 (+https://github.com/HPhucTV/DevRadar)
policy_review:
  status: approved_local_noncommercial_spike
  robots_reviewed_at: 2026-08-21
  terms_reviewed_at: 2026-08-21
  next_review_at: 2026-11-21
```

`aws.momo.vn` chỉ được phép như network host do public career UI tự gọi khi người dùng nhấn `Xem thêm`. Adapter không tự dựng `X-Client-*` header, không replay endpoint nội bộ và không nhận URL/filter từ user hoặc model. Media, analytics và host ngoài allow-list phải bị browser route policy chặn nếu không cần cho list/detail contract.

## 3. Policy và public-access evidence

| Check | Evidence | Kết quả |
|---|---|---|
| Public list/detail | [Job list](https://momo.careers/jobs-opening), [sample detail](https://momo.careers/jobs/it-business-analyst-ii-17404) | HTTP 200, không login/API key/CAPTCHA trong bounded spike. |
| Public UI path | Job list và frontend behavior ngày 2026-08-21 | SSR trả 12 item ban đầu; một click `Xem thêm` bằng browser công khai tăng lên 24 item. Không tái tạo request token. |
| Robots | [career robots](https://momo.careers/robots.txt), `https://aws.momo.vn/robots.txt` | Cả hai trả HTTP 404; không có directive cấm, nhưng sự vắng mặt không được diễn giải thành permission. |
| Terms | Career footer và official-site search ngày 2026-08-21 | Không tìm thấy content-use/automated-retrieval terms dành cho career site; các terms tìm thấy trên `momo.vn` là service-specific. Đây là operator gate, không phải license ngầm. |
| Privacy | Job list/detail và application boundary | DevRadar chỉ đọc posting; không nhấn `Ứng tuyển`, không submit form và không thu candidate data. |
| Contact/takedown | [Hướng dẫn gửi yêu cầu hỗ trợ](https://www.momo.vn/huong-dan/huong-dan-gui-yeu-cau-ho-tro-bang-tinh-nang-tro-giup), career footer | Hotline `1900 5454 41` và kênh trợ giúp chính thức; operator phải pause source ngay khi có yêu cầu. |

Review này là engineering gate, không phải tư vấn pháp lý. Việc trang công khai và không có robots/terms riêng không cấp quyền tái xuất bản hoặc khai thác thương mại.

## 4. Technical evidence

Bounded spike ngày 2026-08-21 với User-Agent đã khai báo:

| Request / interaction | Status | Response bytes | Observation |
|---|---:|---:|---|
| `GET /jobs-opening` | 200 | 96,349 | SSR `__NEXT_DATA__`: `TotalItems=107`, `Count=12`, `PageCount=9`, 12 item ban đầu |
| `GET /jobs-opening?groups=DGM.0001` | 200 | 99,933 | `TotalItems=37`, `Count=12`, `PageCount=4`, filter trả đúng `DGM.0001` |
| public UI `Xem thêm` | pass | — | số job link tăng 12 → 24; button vẫn còn cho batch sau |
| `GET /jobs/it-business-analyst-ii-17404` | 200 | 62,969 | detail có `jobId=17404`, `jobCode=26-T&H_ITC-0260` |

Các số liệu chỉ chứng minh shape và UI flow tại thời điểm review, không phải baseline production hoặc bằng chứng full crawl.

### List/detail boundary

- Navigate duy nhất tới `/jobs-opening?groups=DGM.0001`; group ID/name phải khớp master data trong SSR payload.
- Parse `__NEXT_DATA__` để lấy `TotalItems`, `PageCount`, batch đầu và listing identity.
- Khi số item nhỏ hơn `TotalItems`, browser nhấn đúng button `Xem thêm`, chờ network/DOM ổn định và kiểm tra batch tăng; không gọi API nền trực tiếp.
- ListingRef tối thiểu gồm `jobId`, `jobCode`, `jobTitle`, `location`, `jobType`, `subdirectory` và canonical detail URL.
- Detail URL chỉ được tạo từ `base_url` và `subdirectory` đã xuất hiện trong approved list flow.
- Không nhấn `Ứng tuyển`, `Giới thiệu bạn bè`, tải attachment hoặc gọi application endpoint.

### Identity

- Primary identity: `(source_id, jobId)`.
- `jobCode` và canonical URL là provenance/cross-check, không thay primary identity.
- `subdirectory` phải kết thúc bằng cùng `jobId`; mismatch làm item bị reject/review.
- Cùng `jobId` với slug mới cập nhật URL observation; không tạo Job mới.
- Thiếu/trùng `jobId` khác nội dung làm run `partial`; không fallback sang title hash.

### Run completeness

Run chỉ có `coverage_status=complete` khi:

1. SSR payload hợp lệ, filter là đúng `DGM.0001`, `TotalItems >= 0`, `PageCount >= 1` và batch đầu không vượt 12;
2. mỗi click `Xem thêm` hoàn tất trong timeout, tăng số unique `jobId` từ 1 đến 12 và không thay đổi filter;
3. quá trình dừng khi unique item count đúng bằng `TotalItems`, button biến mất và observed batch count không vượt `PageCount`;
4. mọi `jobId/jobCode/subdirectory` hợp lệ, không conflict và detail bắt buộc theo fixture policy tải thành công;
5. `TotalItems/PageCount` không đổi bất thường trong run; nếu đổi, run là `incomplete` và được retry ở run mới.

Button biến mất sớm, token/control thay đổi, click không tăng item, count conflict, browser crash, schema đổi hoặc navigation ra ngoài allow-list đều làm run `partial/incomplete`. V1 không kích hoạt missing/removal.

## 5. Extraction và data handling

- Dùng SSR structured data cho batch đầu và DOM/listing data sau public load-more; browser chỉ giải quyết pagination thực sự cần JavaScript.
- Không tái tạo encryption/request token từ JavaScript bundle và không dùng direct API như một undocumented HTTP adapter.
- Không dùng LLM trong V1.
- Chỉ lưu posting fields và sanitized description; bỏ application fields, tracking, widget, media và unrelated footer content.
- Giữ raw title/location/job type/job code/division cùng snapshot/provenance trước normalization.
- Không ingest email/phone cá nhân nếu vô tình xuất hiện trong JD; đánh dấu review/redact theo policy dữ liệu.
- Public API V1 chạy local/private; raw HTML không được trả user-facing.

## 6. Failure, throttle và source health

- Một browser page, concurrency 1; cách ít nhất 5 giây giữa load-more/detail actions.
- Tôn trọng `Retry-After`; không đổi User-Agent, header, proxy hoặc browser fingerprint để vượt 401/403/429/challenge.
- Chỉ navigation document trên `momo.careers`; chỉ cho network request cần thiết tới exact MoMo career path trên `aws.momo.vn`. Redirect/navigation ngoài allow-list bị block.
- Response/document ngoài content type dự kiến hoặc vượt 2 MB bị policy-blocked.
- `X-Client-*` control, CAPTCHA/challenge, robots/terms mới hoặc direct-API requirement làm source pause; không reverse-engineer để tiếp tục.
- Count giảm bất thường, group ID/name đổi hoặc load-more lỗi làm source degraded/quarantined; không suy ra job removed.

## 7. Fixture và smoke plan

Fixture cần capture sau khi operator approve, đã loại tracking/PII không cần thiết:

- SSR list `groups=DGM.0001` và master-data mapping;
- DOM/list batch sau một lần `Xem thêm`;
- detail IT happy path;
- missing optional job type/location/job code;
- duplicate `jobId`, slug mismatch và slug change;
- `TotalItems/PageCount` conflict;
- button biến mất sớm, click không tăng item và browser timeout;
- unsafe detail markup, redirect/navigation ngoài allow-list;
- 403/429/challenge hoặc request-control change.

Live smoke tối đa một filtered list navigation, một `Xem thêm` interaction và một detail. Full on-demand run chỉ được mở sau fixture tests, browser route allow-list và incomplete-run behavior pass.

## 8. Approval checklist

| Gate | Status |
|---|---|
| Public, no auth/bypass | Pass qua public browser UI; direct API replay bị cấm |
| Robots reviewed | Pass; 404 được ghi là absence, không phải permission |
| Stable identity | Pass |
| List/detail và completeness strategy | Pass với browser load-more invariant |
| Rate/timeout/redirect/size limits | Pass as conservative proposal |
| Vietnam IT scope | Pass qua `DGM.0001` |
| Browser necessity | Pass; HTTP SSR chỉ có batch đầu |
| Contact/takedown | Pass |
| Employer content-use scope | Operator chấp nhận bounded local non-commercial scope; public/commercial use chưa được duyệt |
| Operator approval | Pass — user decision ngày 2026-08-21 |

## 9. Phạm vi approval

Operator decision ngày 2026-08-21 cho phép:

- bounded fixture/browser spike và on-demand ingestion khi phát triển local V1;
- lưu raw snapshot/canonical data trong môi trường local, theo retention/security contract;
- dùng public career UI với fixed IT group `DGM.0001`, exact allow-list và throttling ở trên;
- mở detail từ listing identity đã quan sát.

Không được kế thừa approval này cho public full-JD exposure, scheduled/public crawl, commercial reuse, direct replay của frontend API, external LLM hoặc AI training. Thay đổi terms/robots/control hoặc mở rộng phạm vi phải pause và re-review trước.
