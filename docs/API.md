# REST API contract

## 1. Phạm vi và trạng thái

DevRadar cung cấp REST JSON dưới `/api/v1`. OpenAPI tại `/api/v1/openapi.json` là wire contract chính cho endpoint đã triển khai; tài liệu này giữ intent, quyền truy cập và phase availability cho cả phần đã có và phần còn planned.

V2 hiện đã triển khai process health, bảy endpoint đọc Job/JobChange/Source/CrawlRun và một local-gated CrawlRun mutation trong bảng dưới. OpenAPI và PostgreSQL contract test là nguồn bằng chứng wire behavior.

## 2. Quy ước

- URL dùng plural noun, không dùng động từ: `/jobs`, `/crawl-runs`, `/resume-profiles`.
- JSON field và query parameter dùng `camelCase`; enum value dùng `lower_snake_case` như domain model.
- Timestamp là UTC ISO 8601, ví dụ `2026-08-21T08:00:00Z`.
- ID là opaque string.
- Field chưa biết trả `null`; field không được phép xem sẽ bị omit, không trả placeholder.
- List endpoint luôn có pagination và deterministic ordering.
- Error luôn theo một envelope; không trả stack trace, SQL, source payload hoặc secret.
- API không nhận crawler URL tùy ý. Client chọn `sourceId` đã được approved.

## 3. Envelope

### 3.1. Một resource

```json
{
  "data": {
    "id": "opaque-id"
  }
}
```

### 3.2. Danh sách

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 0,
    "totalPages": 0
  }
}
```

V1 dùng page-based pagination vì dataset portfolio còn bounded và UI cần total count. `page` bắt đầu từ 1; `pageSize` mặc định 20, tối đa 100. Default order của `/jobs` là `lastSeenAt desc` rồi `id asc` để ổn định khi timestamp trùng.

### 3.3. Error

```json
{
  "error": {
    "code": "validation_error",
    "message": "Request không hợp lệ.",
    "details": [
      {
        "field": "pageSize",
        "reason": "must_be_less_than_or_equal_to_100"
      }
    ],
    "requestId": "opaque-correlation-id"
  }
}
```

`message` dành cho người đọc và có thể được cải thiện; client chỉ được branch theo `code`. `details` phải được allow-list và không chứa input value hoặc dữ liệu nội bộ. Mọi error response hiện có `X-Request-ID` trùng `requestId`; `500`/`503` không trả exception, SQL hoặc dependency payload.

## 4. HTTP semantics

| Status | Nghĩa |
|---|---|
| `200` | Đọc hoặc thao tác đồng bộ thành công. |
| `201` | Resource được tạo đồng bộ. |
| `202` | Crawl/match job đã được chấp nhận, chưa hoàn tất. |
| `204` | Xóa thành công, không có body. |
| `400` | Syntax/query combination không hợp lệ. |
| `401` | Chưa xác thực. |
| `403` | Đã xác thực nhưng không đủ quyền hoặc source/action bị policy chặn. |
| `404` | Resource không tồn tại hoặc không được phép tiết lộ. |
| `409` | Conflict/idempotency/version state. |
| `413` | Upload/request vượt giới hạn. |
| `415` | Content type không hỗ trợ. |
| `422` | Dữ liệu đúng cú pháp nhưng không đạt schema/domain validation. |
| `429` | Rate limit. |
| `500` | Lỗi nội bộ đã sanitize. |
| `503` | Dependency tạm thời không sẵn sàng. |

## 5. Endpoint theo phase

| Method và path | Mục đích | Phase | Quyền tối thiểu |
|---|---|---|---|
| `GET /api/v1/health` | Process liveness; không tuyên bố database/source readiness | V1 scaffold | local/read |
| `GET /api/v1/jobs` | List/filter canonical jobs | V1 — implemented | local/read; public read policy ở V6 |
| `GET /api/v1/jobs/{jobId}` | Job detail và provenance tóm tắt | V1 — implemented | local/read |
| `GET /api/v1/sources` | Source và health summary | V1 — implemented | local/read; không lộ policy secret |
| `GET /api/v1/sources/{sourceId}` | Source detail đã sanitize | V1 — implemented | local/read |
| `GET /api/v1/crawl-runs` | List crawl runs | V1 — implemented | operator/read |
| `GET /api/v1/crawl-runs/{runId}` | Run detail, metric và safe error | V1 — implemented | operator/read |
| `GET /api/v1/jobs/{jobId}/changes` | Lịch sử thay đổi | V2 — implemented | local/read |
| `POST /api/v1/crawl-runs` | Tạo pending run cho source approved | V2 — implemented | local/operator write gate |
| `GET /api/v1/skills` | Taxonomy và frequency | V3 | local/read |
| `GET /api/v1/skill-trends` | Cohort/time-window trend | V3 | local/read |
| `GET /api/v1/agent-runs` | Audit run đã redact | V4 | operator/read |
| `GET /api/v1/agent-runs/{runId}` | Agent decision và provenance an toàn | V4 | operator/read |
| `POST /api/v1/resume-profiles` | Upload và tạo profile | V5 | owner/write; local-only nếu chưa auth |
| `GET /api/v1/resume-profiles/{profileId}` | Profile đã sanitize | V5 | owner/read |
| `DELETE /api/v1/resume-profiles/{profileId}` | Xóa profile và dữ liệu liên quan theo policy | V5 | owner/write |
| `GET /api/v1/resume-profiles/{profileId}/matches` | List match có component score | V5 | owner/read |
| `GET /api/v1/alert-rules` | List rule của owner | V5 | owner/read |
| `POST /api/v1/alert-rules` | Tạo rule | V5 | owner/write |
| `PATCH /api/v1/alert-rules/{ruleId}` | Sửa field được hỗ trợ | V5 | owner/write |
| `DELETE /api/v1/alert-rules/{ruleId}` | Xóa rule idempotent | V5 | owner/write |

Endpoint V5 chứa CV/owner data phải bị disable trên public deployment cho tới khi V6 có authentication và authorization. Không coi UUID khó đoán là access control.

V2 Source summary bổ sung `consecutiveFailures` và safe `healthReasonCode`; Source detail bổ sung `baselineItemsFound` và `quarantinedAt`. Response không trả rate policy, allowed hosts nội bộ, request payload hoặc raw error. `healthStatus=quarantined` luôn có `quarantinedAt`; các status khác trả `null`.

## 6. Resource contracts cốt lõi

### 6.1. Job summary

```json
{
  "id": "job-id",
  "title": "Backend Developer",
  "companyName": "ABC Tech",
  "location": {
    "raw": "Ho Chi Minh City",
    "city": "Ho Chi Minh City",
    "workMode": null
  },
  "salary": {
    "raw": "15-25 triệu/tháng",
    "min": 15000000,
    "max": 25000000,
    "currency": "VND",
    "period": "month"
  },
  "levels": ["junior"],
  "status": "active",
  "postedAt": null,
  "firstSeenAt": "2026-08-21T08:00:00Z",
  "lastSeenAt": "2026-08-21T08:00:00Z",
  "source": {
    "id": "source-id",
    "name": "Example",
    "url": "https://careers.example.test/jobs/123"
  }
}
```

Job detail V1 thêm plaintext description và current snapshot metadata gồm ID, source URL, fetch time, HTTP/content type và parse status. Raw content, raw hash, HTML và internal snapshot error không được trả. Skill/provenance extraction summary chỉ xuất hiện từ V3 sau khi contract tương ứng được triển khai.

Source response chỉ trả identity, adapter key, approval/health và review/last-run timestamps. `rateLimitPolicy`, `allowedHosts` cùng mọi credential/config nội bộ bị omit khỏi public schema.

### 6.2. CrawlRun

```json
{
  "id": "run-id",
  "sourceId": "source-id",
  "triggerType": "manual",
  "requestedAt": "2026-08-21T07:59:59Z",
  "scheduledFor": null,
  "retryOfRunId": null,
  "attemptNumber": 1,
  "status": "succeeded",
  "coverageStatus": "complete",
  "startedAt": "2026-08-21T08:00:00Z",
  "finishedAt": "2026-08-21T08:03:00Z",
  "counts": {
    "itemsFound": 153,
    "itemsNew": 18,
    "itemsUpdated": 7,
    "itemsMissing": 0,
    "itemsRemoved": 0,
    "itemsReactivated": 0,
    "itemsFailed": 0
  },
  "healthSignalCode": null,
  "error": null
}
```

`POST /crawl-runs` hiện nhận đúng `{"sourceId":"uuid"}`. URL, adapter path, arbitrary header, secret và option chưa support đều bị `422`. Header `Idempotency-Key` là bắt buộc; cùng key và local principal/request trả cùng pending run, khác payload trả `409`. Raw key được hash trước persistence. Endpoint trả `202`, không gọi network trong HTTP request.

Pending run được process `work-one` claim ngoài HTTP lifecycle. Claim giữ nguyên run ID/request provenance; nếu lỗi transient, retry là CrawlRun mới liên kết qua `retryOfRunId`. Nhiều worker process cùng lúc không được xử lý cùng pending row nhờ PostgreSQL row lock và active-run constraint.

Write endpoint chỉ hoạt động khi local deployment đặt `DEVRADAR_OPERATOR_WRITE_ENABLED=true`; default là `false`. Gate này không phải authentication và không được dùng để bảo vệ public mutation. Public exposure phải chờ auth/authorization V6.

`GET /crawl-runs` trả counters, retry/schedule relation, safe health signal và `error.code`; `error.message` không phản chiếu `error_summary` trong database. Default order là `startedAt desc nulls last`, sau đó `id asc`. Pending run có `startedAt/finishedAt=null`.

`GET /jobs/{jobId}/changes` trả page envelope với `changeType`, `fieldName`, old/new JSON value, `crawlRunId`, from/to snapshot ID và `detectedAt`; order là `detectedAt desc, id asc`. Description change chỉ expose hash evidence đã persist, không trả raw snapshot/HTML.

### 6.3. ResumeProfile upload

- Request dùng `multipart/form-data` với đúng một file và optional preference fields đã allow-list.
- MIME header, extension và magic bytes đều được kiểm tra; parser không tin tên file.
- Giới hạn size/page/type được khóa khi V5 bắt đầu dựa trên parser đã chọn và threat model; trước đó endpoint không tồn tại.
- Response không trả raw text, absolute path, embedding hoặc provider payload.
- `DELETE` phải xóa/expire profile, embeddings, matches và retained artifacts theo documented retention policy; audit record không chứa content.

### 6.4. JobMatch

```json
{
  "jobId": "job-id",
  "overallScore": 0.78,
  "components": {
    "skill": 0.85,
    "semantic": 0.79,
    "experience": 1.0,
    "location": 1.0,
    "level": 0.8
  },
  "matchedSkills": ["Python", "FastAPI", "PostgreSQL"],
  "missingSkills": ["Redis", "Kafka"],
  "explanation": "...",
  "scoringVersion": "v1",
  "createdAt": "2026-08-21T08:00:00Z"
}
```

Score là ranking heuristic, không phải xác suất được tuyển. Client phải hiển thị version/explanation phù hợp và không được ngụ ý bảo đảm kết quả tuyển dụng.

## 7. Filtering và sorting

`GET /jobs` hỗ trợ additive query parameters theo phase:

- V1: `page`, `pageSize`, `status`, `sourceId`, `company`, `title`, `location`, `level`, `salaryMin`, `salaryMax`, `seenAfter`, `seenBefore`, `sortBy`, `sortOrder`; `level` match theo membership trong `levels`;
- V3: `skill`, `query`, `searchMode=keyword|semantic`;
- V5: `minMatchScore` chỉ trong profile match context, không dùng trên public job list nếu thiếu `profileId`/owner authorization.

Unknown query parameter trả `422` để tránh client tưởng filter đang hoạt động. Sort field dùng allow-list; không chuyển trực tiếp tên field vào SQL.

Trong V1:

- `company`, `title`, `location` là literal case-insensitive substring; wildcard do client gửi không được diễn giải như SQL wildcard;
- `salaryMin`/`salaryMax` dùng interval overlap trên amount đã normalize, không quy đổi currency và không match record thiếu toàn bộ amount;
- `seenAfter`/`seenBefore` áp vào `lastSeenAt`; timestamp phải có UTC offset và hai đầu range phải đúng thứ tự;
- `sortBy` allow-list gồm `lastSeenAt`, `firstSeenAt`, `postedAt`, `title`, `companyName`, `salaryMin`; null luôn ở cuối và `id asc` là tie-break;
- range sai thứ tự, text chỉ có whitespace, unknown parameter, enum/UUID sai hoặc vượt pagination limit trả `422` trong error envelope chuẩn.

`GET /skill-trends` bắt buộc có hoặc áp dụng rõ default cho `from`, `to`, `cohort`, `granularity`; response luôn trả denominator/sample size để tránh insight gây hiểu nhầm.

## 8. Authentication, authorization và exposure

- V1–V4 mặc định bind local/private network; mutation chỉ dành cho operator được cấu hình ngoài request.
- Có thể public read-only job/skill data trước V6 chỉ sau security/deployment review; crawler run, source config, agent audit và raw evidence vẫn protected.
- V5 CV/alert feature chạy local-only nếu auth chưa có.
- V6 phải có owner check trên mọi ResumeProfile, JobMatch và AlertRule; operator role riêng cho crawl/agent/source operations.
- CORS dùng explicit origin allow-list; không dùng wildcard với credential.
- Error `404` có thể được dùng thay `403` cho owner resource để tránh resource enumeration.

Auth mechanism cụ thể cần ADR khi V6 bắt đầu; tài liệu này không giả định JWT, session hay provider trước khi có quyết định.

## 9. Compatibility và versioning

- Thay đổi additive dùng optional field hoặc endpoint mới.
- Không đổi type/meaning, xóa field hoặc đổi enum đã phát hành trong `/api/v1` nếu thiếu migration/deprecation plan.
- Không để response ordering, raw error text hoặc internal database field vô tình thành contract.
- API schema và contract test được cập nhật trong cùng change với implementation.
- Nếu breaking change là cần thiết, viết ADR và tạo `/api/v2`; không duy trì nhiều version lâu hơn migration window đã công bố.

## 10. Contract tests bắt buộc

- Mọi endpoint có typed request/response và thống nhất envelope.
- List endpoint enforce pagination limit và stable ordering.
- Unknown filter/sort field bị reject.
- Không response nào lộ raw HTML, CV text, embedding, stack trace hoặc secret.
- Source chưa approved và arbitrary URL không thể tạo crawl run.
- Idempotency key retry không tạo hai run.
- ResumeProfile/Match của owner khác trả `404/403` theo policy.
- Upload sai magic bytes, quá lớn, parser timeout hoặc malformed bị reject/cleanup.
- Field addition giữ backward compatibility; breaking fixture phải fail contract test.
