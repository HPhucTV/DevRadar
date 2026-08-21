# Domain model

## 1. Mục đích

Tài liệu này là ubiquitous language của DevRadar. Tên entity, enum và state transition ở code, database, API, metric và UI phải dùng cùng nghĩa. Schema vật lý có thể thay đổi qua migration, nhưng không được đổi semantics mà thiếu cập nhật tài liệu và compatibility plan.

## 2. Quy ước chung

- ID nội bộ là opaque identifier; API client không được suy luận ý nghĩa từ ID.
- Timestamp lưu UTC theo ISO 8601; UI có thể hiển thị `Asia/Ho_Chi_Minh`.
- Enum truyền qua API dùng `lower_snake_case`.
- Raw value phải được giữ khi normalization có thể mất thông tin.
- `null` nghĩa là nguồn không cung cấp hoặc hệ thống chưa xác định; không dùng giá trị giả như `0`, `unknown salary` hoặc ngày hiện tại.
- Tiền dùng amount dạng decimal/integer an toàn, ISO 4217 currency và period riêng; V1 không tự đổi currency.
- Job content và CV là untrusted data, không phải instruction cho agent hoặc tool.

## 3. Thuật ngữ

| Thuật ngữ | Nghĩa chuẩn |
|---|---|
| Source | Một nguồn tuyển dụng đã đăng ký cùng policy crawl. |
| CrawlRun | Một lần chạy có boundary, metric và kết quả hoàn chỉnh/không hoàn chỉnh rõ ràng. |
| RawJobSnapshot | Bằng chứng bất biến cho một response/job observation tại một thời điểm. |
| Job | Canonical listing của một source; chưa tự động đồng nhất với listing tương tự ở source khác. |
| JobChange | Từ V2, thay đổi có ý nghĩa giữa hai phiên bản canonical của cùng Job. |
| DuplicateCandidate | Liên kết gợi ý hai Job có thể cùng cơ hội tuyển dụng; không phải auto-merge. |
| Skill | Khái niệm kỹ năng chuẩn hóa trong taxonomy có version. |
| ExtractionResult | Kết quả parser/LLM có schema, provenance, version và validation status. |
| ResumeProfile | Hồ sơ có cấu trúc được trích từ CV; không đồng nghĩa file CV gốc. |
| JobMatch | Kết quả match có tổng điểm, component score, evidence và scoring version. |
| AgentRun | Một quyết định AI/agent được audit với input reference, output, model và cost. |
| AlertRule | Tiêu chí người dùng muốn theo dõi. |
| AlertDelivery | Một lần gửi thông báo có idempotency và trạng thái delivery. |

Implementation V1 hiện map `Source`, `CrawlRun`, `RawJobSnapshot` vào module `ingestion`, `Job` vào `catalog`, dùng UUID/PostgreSQL constraint để giữ provenance và source-scoped identity. Physical mapping/migration không kích hoạt `JobChange` hoặc absence workflow; xem [ADR-005](decisions/0005-sqlalchemy-alembic-and-psycopg.md) và [V1-002 evidence](evidence/V1-002-postgresql-schema.md).

## 4. Entity chính

### 4.1. Source

| Field logic | Ý nghĩa |
|---|---|
| `id`, `name`, `base_url` | Định danh nội bộ và phạm vi nguồn. |
| `adapter_key` | Parser/adapter được phép dùng; không nhận module path tùy ý từ request. |
| `approval_status` | `candidate`, `approved`, `paused`, `retired`. |
| `health_status` | `unknown`, `healthy`, `degraded`, `unhealthy`, `quarantined`. |
| `crawl_frequency` | Lịch đã duyệt; V1 có thể chạy on-demand. |
| `rate_limit_policy` | Request rate/concurrency/timeout/response limit. |
| `allowed_hosts` | Host và redirect target allow-list. |
| `terms_reviewed_at`, `robots_reviewed_at` | Bằng chứng review source gate. |
| `last_crawled_at`, `last_success_at` | Tình trạng vận hành gần nhất. |

`approval_status` và `health_status` độc lập: source có thể hợp lệ về policy nhưng đang lỗi kỹ thuật.

### 4.2. CrawlRun

| Field logic | Ý nghĩa |
|---|---|
| `id`, `source_id` | Định danh run và source. |
| `trigger_type` | `manual`, `scheduled`, `retry`, `replay`. |
| `started_at`, `finished_at` | Boundary thời gian. |
| `status` | `pending`, `running`, `succeeded`, `partial`, `failed`, `cancelled`. |
| `coverage_status` | `unknown`, `complete`, `incomplete`; tách khỏi technical status. |
| counters | pages/items found/new/updated/missing/removed/failed. |
| `error_code`, `error_summary` | Lỗi đã sanitize; không chứa raw response, secret hoặc PII. |
| `adapter_version`, `config_version` | Khả năng tái hiện run. |

Chỉ run `succeeded` và `coverage_status=complete` được dùng để tăng missing count.

### 4.3. RawJobSnapshot

| Field logic | Ý nghĩa |
|---|---|
| `id`, `crawl_run_id`, `source_id` | Provenance của observation. |
| `source_url`, `external_id` | Identity lấy từ nguồn nếu có. |
| `fetched_at`, `http_status`, `content_type` | Fetch metadata. |
| `raw_content_hash` | Hash của payload canonicalized đủ để cache/replay. |
| `storage_ref` hoặc bounded raw content | Vị trí evidence; cách lưu vật lý được chọn trong V1 scaffold. |
| `parse_status` | `pending`, `parsed`, `invalid`, `failed`, `skipped`. |
| `error_code` | Error taxonomy, không chứa payload nhạy cảm. |

Snapshot là append-oriented. Reparse không sửa snapshot; nó tạo `ExtractionResult` mới.

### 4.4. Job

| Nhóm field | Field logic |
|---|---|
| Identity | `id`, `source_id`, `external_id`, `canonical_url` |
| Nội dung | `title`, `company_name`, `description_text` |
| Location | `location_raw`, normalized city/province, work mode khi có evidence |
| Salary | `salary_raw`, `salary_min`, `salary_max`, `currency`, `salary_period` |
| Requirement | `level_raw`, `levels`, `experience_min`, `experience_max` |
| Time | `posted_at`, `first_seen_at`, `last_seen_at`, `removed_at` |
| State | `status`, `consecutive_missing_count` |
| Provenance | `current_snapshot_id`, `job_content_hash`, extractor/version reference |

`Job` là canonical record trong phạm vi một source. V1 không auto-merge hai Job khác source.

`levels` là tập có thứ tự từ enum `intern`, `fresher`, `junior`, `mid`, `senior`, `lead`, `manager`. Posting “Junior/Mid” được lưu `level_raw` và `levels=[junior, mid]`; không tạo composite enum mơ hồ. Nếu không có evidence, danh sách rỗng thay vì suy đoán từ số năm kinh nghiệm.

### 4.5. JobChange (V2+)

| Field logic | Ý nghĩa |
|---|---|
| `id`, `job_id` | Định danh event. |
| `from_snapshot_id`, `to_snapshot_id` | Evidence hai phía. |
| `field_name` | Field canonical đã đổi. |
| `old_value`, `new_value` | Giá trị typed/serialized phù hợp. |
| `change_type` | `created`, `updated`, `missing`, `removed`, `reactivated`. |
| `detected_at` | Thời điểm hệ thống xác nhận thay đổi. |

Thay đổi markup, tracking parameter hoặc thứ tự không có nghĩa không được tạo event nếu canonical content không đổi.

### 4.6. Skill và JobSkill

`Skill` gồm `name`, `normalized_name`, `category`, aliases và `taxonomy_version`. Category ban đầu: `language`, `framework`, `database`, `cloud`, `devops`, `messaging`, `testing`, `ai`, `tool`, `other`.

`JobSkill` liên kết Job–Skill với:

- `requirement_type`: `required`, `preferred`, `optional`, `mentioned`;
- `confidence`;
- evidence span/reference;
- `extraction_result_id` và extractor/model version.

Alias mới không được merge skill lịch sử âm thầm; taxonomy change cần version và reprocessing plan.

### 4.7. ExtractionResult

| Field logic | Ý nghĩa |
|---|---|
| `input_type`, `input_ref`, `input_hash` | Input được xử lý mà không copy payload vào log. |
| `extractor_type` | `structured_data`, `selector`, `rule`, `llm`. |
| `extractor_version`, `model`, `prompt_version` | Reproducibility. |
| `output_data` | Typed output theo schema version. |
| `validation_status` | `accepted`, `rejected`, `needs_review`. |
| `confidence`, `validation_errors` | Evidence quality. |
| `latency_ms`, token/cost fields | Operation metric khi dùng model. |

### 4.8. ResumeProfile

| Field logic | Ý nghĩa |
|---|---|
| `id`, optional owner reference | Identity và ownership khi auth tồn tại. |
| `file_name_sanitized`, `content_hash` | Audit mà không dùng path/tên tùy ý. |
| structured profile | skill, experience, role preference, location preference. |
| `embedding`/reference | Chỉ từ V3/V5 và có model version. |
| `retention_mode`, `expires_at` | Mặc định ephemeral/short-lived. |

File CV gốc không phải entity lưu trữ lâu dài mặc định. Raw text không được ghi vào log hoặc AgentRun.

### 4.9. JobMatch

`JobMatch` liên kết `ResumeProfile` và `Job`, lưu:

- `overall_score`;
- component score như skill, semantic, experience, location và level;
- matched/missing skill reference;
- evidence và explanation;
- `scoring_version`, embedding/model version;
- `created_at` và stale marker khi Job/Profile đổi.

Trọng số cụ thể là `Proposed` cho tới khi V5 có labeled examples. Không ghi “82% match” như xác suất tuyển dụng.

### 4.10. AgentRun, AlertRule và AlertDelivery

`AgentRun` lưu agent name/version, input reference/hash, decision schema, status, retry relation, latency và cost. Không copy raw CV/JD đầy đủ vào trace.

`AlertRule` lưu filter/match threshold, channel, enabled state và owner. `AlertDelivery` lưu rule/job/job-version, idempotency key, attempt, result và provider message reference đã sanitize.

## 5. Lifecycle

### 5.1. Job lifecycle

```mermaid
stateDiagram-v2
    [*] --> active: first valid observation
    active --> active: observed or meaningful update
    active --> missing: absent in 1 complete successful run
    missing --> active: observed again
    missing --> removed: absent in next complete successful run
    removed --> active: observed again
```

Default là hai run complete liên tiếp để chuyển từ `active` sang `removed`: run đầu tạo `missing`, run tiếp theo tạo `removed`. Source có thể đề xuất threshold cao hơn trong approval record, nhưng không được thấp hơn mặc định nếu thiếu bằng chứng. `partial`, `failed`, `cancelled` hoặc coverage `unknown/incomplete` không tăng counter.

Trong V1, Job luôn ở `active` sau observation hợp lệ; `missing`, `removed`, `reactivated` và `JobChange` chưa được kích hoạt.

### 5.2. Source lifecycle

```text
candidate → approved ↔ paused → retired
                 │
                 └─ health: healthy/degraded/unhealthy/quarantined
```

`quarantined` là health control tự động/tạm thời; `paused` là quyết định operator về quyền chạy.

### 5.3. Extraction lifecycle

```text
input → deterministic extraction → accepted
                           └─────→ incomplete → LLM allowed? → validate
                                                         ├─ accepted
                                                         ├─ needs_review
                                                         └─ rejected
```

## 6. Identity, deduplication và hashing

Thứ tự identity trong cùng source:

1. stable `external_id` do source cung cấp;
2. normalized canonical URL đã bỏ tracking parameter được duyệt;
3. nếu không có 1 hoặc 2, source chưa đủ điều kiện V1; không thay bằng fingerprint suy đoán.

Fingerprint từ company/title/location và embedding similarity chỉ tạo `DuplicateCandidate`. Auto-merge cross-source nằm ngoài V1 vì false positive có thể làm mất provenance và lịch sử riêng.

Hai hash có mục đích khác nhau:

- `raw_content_hash`: cache/replay raw payload;
- `job_content_hash`: phát hiện thay đổi trên tập canonical field đã định nghĩa, bỏ volatile markup/metadata.

## 7. Domain invariants

- Không có Job hợp lệ nếu thiếu source identity, source URL, title, company representation, first/last seen hoặc current snapshot reference.
- `salary_min <= salary_max` khi cả hai có mặt; không suy ra amount từ “competitive” hoặc range không rõ period.
- `last_seen_at >= first_seen_at` và không lấy crawl time làm `posted_at` giả.
- `removed_at` chỉ có khi status `removed`; reactivation giữ lịch sử cũ bằng JobChange.
- Từ V2, không tạo JobChange khi `job_content_hash` không đổi.
- Một JobSkill phải có evidence/extraction provenance.
- Match score phải nằm trong `[0, 1]`, có scoring version và component evidence.
- Agent decision không tự trở thành domain state trước deterministic validation/application step.
