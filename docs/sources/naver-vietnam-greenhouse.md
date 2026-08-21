# Source approval record: NAVER Vietnam on Greenhouse

**Source key:** `naver-vietnam-greenhouse`

**Review date:** 2026-08-21

**Approval status:** `approved`

**Operator decision:** `approved_local_noncommercial_spike` — 2026-08-21

## 1. Decision summary

NAVER Vietnam's Greenhouse board đạt technical gate: public Job Board API không cần authentication cho GET, list response có `meta.total`, mỗi posting có numeric `id`, toàn bộ bounded sample thuộc Việt Nam và không cần browser.

Greenhouse công bố dữ liệu GET là public và dành cho custom career sites, nhưng đó không tự động là license tái xuất bản của employer. NAVER Vietnam board chỉ liên kết recruitment data policy; không tìm thấy general content-use terms cấp rõ quyền lưu/hiển thị JD. Operator đã duyệt source chỉ cho local non-commercial spike/on-demand V1 ingestion. Public full JD, commercial reuse và AI training vẫn ngoài approval.

## 2. Proposed registry record

Đây là candidate configuration để review, chưa phải config chạy được:

```yaml
name: NAVER Vietnam Careers via Greenhouse
source_key: naver-vietnam-greenhouse
approval_status: approved
base_url: https://boards-api.greenhouse.io/v1/boards/navervietnam
allowed_hosts:
  - boards-api.greenhouse.io
reference_hosts:
  - job-boards.greenhouse.io
adapter_key: greenhouse_job_board
adapter_scope:
  board_token: navervietnam
discovery_mode: public_json_api
identity_strategy: external_id
external_id_field: id
expected_pagination: single_response_with_meta_total
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
  status: approved_local_noncommercial_spike
  robots_reviewed_at: 2026-08-21
  terms_reviewed_at: 2026-08-21
  next_review_at: 2026-11-21
```

`job-boards.greenhouse.io` chỉ là reference host từ `absolute_url`; crawler không fetch host này vì API `content=true` đã đủ list/detail contract.

## 3. Policy và public-access evidence

| Check | Evidence | Kết quả |
|---|---|---|
| Public board/API | [NAVER Vietnam board](https://job-boards.greenhouse.io/navervietnam), [JSON list](https://boards-api.greenhouse.io/v1/boards/navervietnam/jobs) | HTTP 200, không login/API key/CAPTCHA trong bounded spike. |
| API intent/auth | [Greenhouse Job Board API docs](https://developer.greenhouse.io/job-board.html), [API overview](https://support.greenhouse.io/hc/en-us/articles/10568627186203-Greenhouse-API-overview) | GET Job Board data công khai, authentication không bắt buộc; API dùng để xuất public job board/postings. |
| Robots | [board robots](https://job-boards.greenhouse.io/robots.txt), [API robots](https://boards-api.greenhouse.io/robots.txt) | Board không có active `Disallow`; API chỉ disallow `/embed/`, không chặn `/v1/boards/...`. |
| Employer terms | [NAVER Vietnam recruitment data policy](https://navercorp.vn/en/data_policy.html), board/footer review | Có applicant privacy policy/contact; không tìm thấy general content-use terms cấp rõ quyền syndication. Đây là operator gate. |
| Privacy | NAVER data policy và Greenhouse board | DevRadar chỉ GET posting data; không gọi application endpoint hoặc thu candidate data/question fields. |
| Contact/takedown | NAVER data policy | `dl_dppnvn@navercorp.com`; operator phải pause source ngay khi có yêu cầu. |

Review này là engineering gate, không phải tư vấn pháp lý. Public API availability không được diễn giải thành quyền commercial resale hoặc AI training.

## 4. Technical evidence

Bounded spike ngày 2026-08-21 với User-Agent đã khai báo:

| Request | Status | Response bytes | Observation |
|---|---:|---:|---|
| `GET .../navervietnam/jobs?content=true` | 200 | 157,337 | 14 postings, `meta.total=14`, 14 Vietnam locations |
| một posting detail GET | 200 | 10,882 | public post `id=5733023004`, `internal_job_id=5017714004` |

Các số liệu chỉ chứng minh shape tại thời điểm review, không phải baseline production.

### List/detail boundary

- Discover bằng `GET /v1/boards/navervietnam/jobs?content=true`.
- Board token là literal `navervietnam`; request không nhận board token hoặc URL từ user/model.
- `content=true` trả full published post content trong cùng response, nên V1 không cần detail fan-out.
- Detail endpoint `/jobs/{id}` chỉ dùng cho bounded diagnosis/recovery theo posting ID đã xuất hiện trong list; không bắt buộc trong normal run.
- `absolute_url` trên `job-boards.greenhouse.io` là user-facing reference, không được crawler follow.
- Không gọi application POST, Harvest API, question endpoint hoặc internal board.

### Identity

- Primary identity: `(source_id, public job post id)` từ field `id`.
- `internal_job_id` chỉ là provenance; không dùng làm external identity vì một internal job có thể có nhiều public posts.
- `absolute_url` là canonical reference/fallback sau validation board token/path.
- Thiếu/trùng post `id` khác nội dung làm run `partial`; không fallback sang title/company hash.

### Run completeness

Run chỉ có `coverage_status=complete` khi:

1. list GET trả JSON hợp lệ và `meta.total` là integer không âm;
2. số posting trong `jobs` đúng bằng `meta.total`;
3. union public post `id` không có conflict;
4. mọi posting có `absolute_url` hợp lệ trên reference host và thuộc board `navervietnam`;
5. location thuộc Việt Nam hoặc được đưa vào explicit review/excluded counter, không âm thầm map location mơ hồ.

Count mismatch, duplicate ID conflict, schema đổi, body rỗng bất thường hoặc response vượt limit làm run `partial/incomplete`. Vì một response chứa toàn bộ list, không cần pagination. V1 không kích hoạt missing/removal.

## 5. Extraction và data handling

- JSON API là deterministic source; không browser và không LLM trong V1.
- `content` là HTML entity-encoded theo Greenhouse docs; decode có giới hạn, giữ raw, sanitize và tạo canonical plaintext deterministic.
- Giữ title, location, offices/departments, language, timestamps và metadata raw/provenance trước normalization.
- Không request application `questions=true`; không lưu application form, demographic question, CV hoặc applicant data.
- V1 API local/private có thể trả sanitized description. Public exposure sau này phải re-review terms; mặc định chỉ title, company, location, source link và bounded excerpt nếu chưa có permission rõ.
- Approval V1 không cấp quyền dùng JD cho AI training. LLM extraction V3 cần policy review mới.

## 6. Failure, throttle và source health

- Concurrency 1, tối đa 10 request/phút dù normal run chỉ cần một list request.
- Tôn trọng `Retry-After`; không đổi host/User-Agent hoặc browser để vượt 403/429/challenge.
- Redirect ra ngoài `boards-api.greenhouse.io` bị block; `absolute_url` không được follow.
- Response ngoài JSON đã duyệt hoặc body vượt 2 MB bị policy-blocked.
- `meta.total` mismatch, country/location biến mất hàng loạt, count giảm bất thường hoặc schema đổi làm source degraded/quarantined; không suy ra removed.
- Robots, Greenhouse API docs hoặc NAVER policy thay đổi làm source pause cho tới re-review.

## 7. Fixture và smoke plan

Fixture cần capture sau khi operator approve, đã loại tracking/PII không cần thiết:

- list `content=true` với nhiều departments/locations;
- detail happy path để đối chiếu list content;
- missing optional metadata/department;
- HTML entity decode và unsafe markup sanitation;
- `meta.total` mismatch;
- duplicate public post ID conflict;
- invalid/non-Vietnam location;
- malformed JSON, 429/timeout và redirect ngoài allow-list.

Live smoke tối đa một list request và tùy chọn một detail; không gọi application/Harvest endpoint và không chạy schedule trước khi fixture tests pass.

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
| Greenhouse/employer content-use scope | Operator chấp nhận bounded local non-commercial scope; public/commercial use vẫn chưa được duyệt |
| Operator approval | Pass — user decision ngày 2026-08-21 |

## 9. Phạm vi approval

Operator decision ngày 2026-08-21 cho phép:

- bounded source/fixture spike và on-demand ingestion khi phát triển local V1;
- lưu raw snapshot/canonical data trong môi trường local, theo retention/security contract;
- chỉ dùng public GET dưới board token `navervietnam` trên API host;
- không gọi application, Harvest, question hoặc internal endpoint.

Không được kế thừa approval này cho public full-JD exposure, schedule production, commercial reuse, external LLM hoặc AI training. Thay đổi terms/robots/control hoặc mở rộng phạm vi phải pause và re-review trước.
