# Operations, quality và security gates

## 1. Mục tiêu

Tài liệu này định nghĩa bằng chứng cần có để nói DevRadar chạy đúng, an toàn và có thể chẩn đoán. Ở trạng thái hiện tại chưa có code hoặc command đã xác minh; các gate dưới đây là contract cho phase tương ứng, không phải tuyên bố chúng đã pass.

## 2. Environment

| Environment | Mục đích | Dữ liệu | Exposure |
|---|---|---|---|
| Local | Phát triển, fixture, source spike có kiểm soát | fixture và dữ liệu thật giới hạn | localhost/private |
| CI | Test, static analysis, migration/eval smoke | synthetic/fixture, không có PII | isolated |
| Demo | Portfolio demo từ V5 | dataset đã sanitize; CV ephemeral | protected hoặc read-only |
| Production-like | V6 public deployment | dữ liệu công khai + owner data có policy | HTTPS, auth, monitoring |

Không dùng production secret/data trong CI. Không gọi source/LLM thật từ default unit test; live integration phải opt-in, có budget và được gắn nhãn rõ.

## 3. Configuration và secrets

- Config được parse/validate một lần khi khởi động; thiếu secret bắt buộc phải fail closed.
- `.env.example` chỉ chứa key và placeholder, không chứa credential thật.
- `.env`, local override, key/certificate và exported data phải bị ignore khi scaffold Git.
- API key, database password, session secret, webhook token và source credential không được hardcode hoặc log.
- External provider/source mới phải có owner, mục đích, data classification và rotation/revocation path.
- Nếu secret từng bị commit hoặc lộ trong log, rotate/revoke trước; chỉ xóa khỏi file không đủ.

## 4. Test strategy

### 4.1. Unit tests

Chạy nhanh, deterministic, không network:

- parser/normalizer cho text, URL, location, salary, level, experience và skill;
- identity, hash, idempotency, dedup và Job lifecycle;
- API schema/error/pagination helpers;
- match component/scoring version;
- AI output validator, evidence check, cost/step limit;
- redaction và security policy helpers.

### 4.2. Integration tests

- adapter fixture → RawJobSnapshot → normalized Job → PostgreSQL;
- rerun/reprocess và transaction rollback;
- migration up/down hoặc forward/rollback strategy phù hợp;
- FastAPI → PostgreSQL với OpenAPI/contract assertion;
- V2 scheduler/retry → run state/metrics;
- V3 pgvector query với model-version filter;
- V5 upload parser trong isolated test và owner access control;
- alert retry/idempotency với fake connector.

Test được gọi “PostgreSQL integration” chỉ khi thực sự chạy PostgreSQL, không phải SQLite/mock. Test AI live không được thay thế evaluation trên fixed dataset.

### 4.3. End-to-end và acceptance

- V1: trigger approved adapter qua operator path, ingest dataset và query qua API.
- V2: scheduled run phát hiện new/update/missing/removed mà không false removal khi partial.
- V3: deterministic extraction + LLM fallback trên labeled suite và semantic query.
- V4: invalid extraction đi qua bounded validator decision, retry/review và audit.
- V5: upload CV hợp lệ, xem match/evidence, xóa profile và xác nhận artifact hết hiệu lực.
- V6: public auth, authorization, rate limiting, backup restore và deploy rollback.

## 5. Scenario bắt buộc

| Scenario | Kết quả bắt buộc |
|---|---|
| Replay cùng snapshot | Không duplicate Job hoặc JobChange; metric idempotent. |
| Crawl network/parser fail | Run `partial/failed`; không tăng missing count. |
| Source chưa approved | Bị chặn trước outbound request. |
| Redirect/private address | Bị chặn và ghi safe policy error; không follow. |
| Empty/anomalous source response | Coverage không được coi complete nếu invariant chưa đạt. |
| HTML/JD malformed | Snapshot còn để replay; parser fail có taxonomy. |
| LLM malformed/hallucinated output | Schema/evidence gate reject hoặc bounded retry/review. |
| Prompt injection trong JD/CV | Không đổi tool/policy, không gọi arbitrary action. |
| Upload sai type/magic/size | Reject, cleanup temporary file, không tạo profile dở dang. |
| Upload parser timeout/bomb | Giới hạn tài nguyên, cleanup và safe error. |
| Owner khác đọc CV/match | Bị authorization chặn, không lộ resource existence theo policy. |
| Log/error/trace | Không chứa raw CV, secret, auth header, raw embedding hoặc full payload. |
| Alert retry | Không gửi trùng cùng idempotency key. |

## 6. Security baseline

### 6.1. Assets

- source/database/LLM/notification credentials;
- raw job evidence và dataset integrity;
- CV, ResumeProfile, embedding và match result;
- operator action, agent decision và audit trail;
- compute/budget cho crawler và model.

### 6.2. Controls theo trust boundary

- API input, third-party response và model output đều được schema-validate tại boundary.
- Database access parameterized; migration không chạy từ user input.
- Outbound HTTP dùng source allow-list, DNS/IP/redirect revalidation, timeout và size cap; high-risk production path phải giảm DNS rebinding/TOCTOU qua network egress control hoặc pinned resolution phù hợp.
- Browser crawler áp cùng scheme/host/IP policy cho navigation, iframe, subresource và WebSocket; dùng fresh ephemeral context, chặn service worker/download/popup/external protocol, không cấp camera/microphone/geolocation/clipboard/file access, không dùng persistent cookie/storage và chạy trong sandbox/least-privilege runtime không có secret hoặc host mount không cần thiết.
- HTML hiển thị bằng framework escaping; không render raw source/model HTML.
- File upload kiểm tra extension, MIME và signature; bounded size/page/decompression; parser không thực thi macro/script và chạy với least privilege.
- Authenticated deployment dùng HTTPS, restricted CORS, security headers, secure/httpOnly/sameSite session cookie nếu chọn session strategy.
- Authorization kiểm tra owner/operator ở server trên mọi protected resource.
- Error public generic; detail nội bộ được sanitize và correlation bằng request ID.
- LLM tool default deny, output không đi vào SQL/shell/path/HTML và có token/step/cost cap.
- Dependency/lockfile được audit; finding chỉ được defer khi có reachability assessment, owner và review date.

### 6.3. Abuse cases cần test trước exposure

- attacker dùng source/run API để SSRF vào localhost/cloud metadata;
- source trả redirect qua host approved rồi tới private IP;
- JavaScript page dùng iframe/subresource/WebSocket để truy cập private host, tải file hoặc giữ state qua browser run;
- JD chứa prompt yêu cầu model tiết lộ secret hoặc gọi tool;
- file PDF/DOCX giả mạo, zip bomb hoặc parser exploit;
- anonymous user enumerate ResumeProfile/AgentRun;
- query/filter tạo SQL injection hoặc expensive unbounded query;
- alert rule gây spam/cost amplification;
- crafted dataset làm loop agent hoặc tăng token vô hạn.

## 7. Observability

### 7.1. Correlation

Mỗi request/run/extraction/agent/delivery có opaque ID. Log dùng structured fields và liên kết bằng ID/reference, không copy raw payload.

### 7.2. Metric tối thiểu

| Area | Metrics |
|---|---|
| Crawler | `crawl_runs_total`, `crawl_success_rate`, `crawl_duration_seconds`, `pages_fetched_total`, `response_bytes_total` |
| Data | `jobs_new_total`, `jobs_updated_total`, `jobs_missing_total`, `jobs_removed_total`, `duplicates_candidate_total`, `parse_failures_total` |
| Source | `source_last_success_age`, `source_failure_rate`, `source_coverage_anomalies_total`, health state |
| AI | `ai_requests_total`, `ai_cache_hits_total`, `ai_validation_failures_total`, `ai_latency_seconds`, input/output tokens, estimated cost |
| Agent | `agent_runs_total`, decision/retry/review count, step-limit hit, failure rate |
| API | request count, latency, status code, validation/rate-limit failures |
| CV/alert | upload reject/cleanup, match duration, deletion completion, delivery success/duplicate prevented |

Metric label không chứa URL query, title/company tùy ý, raw skill, CV field, error text hoặc user-provided high-cardinality value.

### 7.3. Log levels và redaction

- `INFO`: state transition và aggregate result;
- `WARN`: degraded/anomaly/retry/review;
- `ERROR`: operation failed với error code và correlation ID;
- debug payload chỉ dùng fixture/sanitized local mode, tắt ở public deployment.

Redact authorization/cookie/token, database DSN credential, prompt/JD/CV content và provider response. Không dựa vào redact regex duy nhất; ưu tiên allow-list structured fields.

## 8. SLO và alerting

Không đặt SLO phần trăm/latency giả trước khi có baseline. Mỗi phase thu baseline trên workload được mô tả rồi ghi target cùng evaluation/release artifact.

Alert vận hành tối thiểu từ V2:

- source không có successful complete run trong expected window;
- failure/partial/anomaly tăng vượt baseline;
- jobs discovered giảm bất thường;
- database/migration/persistence failure;
- V3+ AI budget, validation failure hoặc provider outage;
- V6 auth/rate-limit/security event bất thường.

## 9. Retention, deletion và backup

Default được dùng cho đến khi có ADR thay đổi:

| Data | Default |
|---|---|
| Canonical Job, JobChange, Source, CrawlRun metadata | Giữ để phục vụ lịch sử; review khi dataset tăng. |
| Raw job payload | 90 ngày; hash/provenance metadata giữ lâu hơn để audit. |
| Application logs | 30 ngày ở deployment; local/CI ngắn hơn. |
| Agent/LLM audit metadata | 90 ngày; không giữ full prompt chứa raw content/PII. |
| CV file gốc | Xóa ngay sau parsing thành công/thất bại cleanup. |
| ResumeProfile, embedding, JobMatch khi chưa có auth | Ephemeral, mặc định hết hạn sau 24 giờ. |
| Authenticated saved profile ở V6 | Chỉ khi user opt-in; retention hiển thị rõ và hỗ trợ delete. |

Backup:

- V1–V4 local: document export/restore cho schema và seed/fixture; không tuyên bố durability production.
- Trước demo/public deployment: automated PostgreSQL backup, encrypted storage, retention policy và restore test có timestamp/evidence.
- Backup chứa owner data phải theo cùng access/deletion policy; deletion guarantee phải nói rõ giới hạn backup retention.

## 10. CI gates theo phase

| Phase | Gate bổ sung |
|---|---|
| V1 | format/lint/type check, unit, PostgreSQL integration, migration check, OpenAPI contract, image/config smoke |
| V2 | scheduler/retry/state-transition tests và orchestration smoke |
| V3 | fixed AI evaluation suite, pgvector integration, cost/token report |
| V4 | agent step/tool/policy safety tests và graph regression |
| V5 | frontend build, accessibility baseline, browser E2E, upload/delete/authorization tests |
| V6 | dependency/container scan, secret scan, auth/rate-limit/security header tests, deploy/rollback và restore drill |

Command cụ thể chỉ được thêm vào README/AGENTS sau khi scaffold và chạy thành công. CI không được “green” bằng cách skip silently một gate bắt buộc; live/optional test phải báo rõ trạng thái skipped và lý do.

## 11. Deployment gates

### Local V1

- clean setup từ documented prerequisites;
- migration chạy trên PostgreSQL mới;
- một approved fixture/source run và API smoke;
- teardown không xóa volume/data nếu thiếu explicit operator action.

### Protected demo V5

- dataset license/policy và source attribution được review;
- CV feature local/protected hoặc có auth; no anonymous retention;
- HTTPS, secrets, CORS/security headers và resource limits;
- monitoring, budget limit và cleanup job hoạt động;
- demo claims khớp evidence hiện tại.

### Public V6

- auth/authz, rate limit, privacy/retention và incident contact;
- backup + restore evidence, migration rollback/forward plan;
- vulnerability/reachability review và no unresolved reachable critical/high issue;
- alerting, runbook và rollback được diễn tập;
- Terms/privacy notice phù hợp dữ liệu đang xử lý.

## 12. Runbook tối thiểu

Trước public deployment phải có procedure được kiểm thử cho:

- source degraded/quarantined hoặc terms thay đổi;
- parser regression gây dữ liệu sai;
- database migration/persistence failure;
- LLM provider outage/cost spike/model regression;
- secret exposure;
- CV/PII exposure hoặc deletion failure;
- bad deploy và rollback.

Mỗi incident record nêu impact, time range, affected data/source, containment, recovery evidence và follow-up owner; không đính kèm secret/PII vào ticket/log.
