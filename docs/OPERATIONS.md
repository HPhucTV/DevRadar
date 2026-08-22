# Operations, quality và security gates

## 1. Mục tiêu

Tài liệu này định nghĩa bằng chứng cần có để nói DevRadar chạy đúng, an toàn và có thể chẩn đoán. V1 data pipeline và V2 schedule/retry/lifecycle/health/operator queue đã có verified PostgreSQL, static và bounded live evidence. V3 AI/semantic capability chưa được coi là triển khai cho tới khi fixed evaluation và provider/pgvector gate tương ứng pass.

## 2. Environment

| Environment | Mục đích | Dữ liệu | Exposure |
|---|---|---|---|
| Local | Phát triển, fixture, source spike có kiểm soát | fixture và dữ liệu thật giới hạn | localhost/private |
| CI | Test, static analysis, migration/eval smoke | synthetic/fixture, không có PII | isolated |
| Demo | Portfolio demo từ V5 | dataset đã sanitize; CV ephemeral | protected hoặc read-only |
| Production-like | V6 public deployment | dữ liệu công khai + owner data có policy | HTTPS, auth, monitoring |

Kết quả kiểm tra capability máy phát triển trước V1 được ghi riêng tại [PRE-007 local prerequisites evidence](evidence/PRE-007-local-prerequisites.md); đây không phải Quick Start hoặc runtime proof của ứng dụng.

Kết quả scaffold nằm tại [V1-001 evidence](evidence/V1-001-scaffold.md); fresh PostgreSQL migration/schema integration nằm tại [V1-002 evidence](evidence/V1-002-postgresql-schema.md); safe fetch/raw snapshot boundary nằm tại [V1-004 evidence](evidence/V1-004-safe-fetch-and-snapshot.md); NAVER/VNG/MoMo adapters nằm tại [V1-006](evidence/V1-006-naver-greenhouse-adapter.md), [V1-007](evidence/V1-007-vng-adapter.md) và [V1-008](evidence/V1-008-momo-adapter.md); current-state persistence nằm tại [V1-009 evidence](evidence/V1-009-job-upsert.md); PostgreSQL-backed read contract nằm tại [V1-010 evidence](evidence/V1-010-read-api.md); safe structured events nằm tại [V1-011 evidence](evidence/V1-011-observability.md); on-demand runner cùng Compose browser sandbox nằm tại [V1-012 evidence](evidence/V1-012-compose-and-runner.md); full source/replay inventory nằm tại [V1-013 evidence](evidence/V1-013-live-inventory.md); phase decision và gate mapping nằm tại [V1 closeout](evidence/V1-closeout.md). Health endpoint chỉ chứng minh API process sống; API database behavior và browser sandbox được kiểm tra bằng smoke riêng.

Không dùng production secret/data trong CI. Không gọi source/LLM thật từ default unit test; live integration phải opt-in, có budget và được gắn nhãn rõ.

## 3. Configuration và secrets

- Config được parse/validate một lần khi khởi động; thiếu secret bắt buộc phải fail closed.
- `.env.example` chỉ chứa key và placeholder, không chứa credential thật.
- `.env`, local override, key/certificate và exported data phải bị ignore khi scaffold Git.
- API key, database password, session secret, webhook token và source credential không được hardcode hoặc log.
- `DEVRADAR_OPERATOR_WRITE_ENABLED` mặc định `false`; đây chỉ là local deployment gate, không phải auth. Không bật write API trên public ingress trước V6 auth/authorization.
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
- V3 taxonomy/category, role ambiguity và bounded summary evidence/length validator;
- redaction và security policy helpers.

### 4.2. Integration tests

- adapter fixture → RawJobSnapshot → normalized Job → PostgreSQL;
- safe fetch result → RawJobSnapshot trên PostgreSQL thật, gồm policy/config mismatch, invalid encoding và caller-owned transaction;
- rerun/reprocess và transaction rollback;
- migration up/down hoặc forward/rollback strategy phù hợp;
- FastAPI → PostgreSQL với OpenAPI/contract assertion;
- V2 scheduler/retry → run state/metrics;
- V2 API pending request → `SKIP LOCKED` one-shot claim → ingestion/retry chain, không chạy network trong HTTP request;
- V3 pgvector query với model-version filter;
- V5 upload parser trong isolated test và owner access control;
- alert retry/idempotency với fake connector.

Test được gọi “PostgreSQL integration” chỉ khi thực sự chạy PostgreSQL, không phải SQLite/mock. Test AI live không được thay thế evaluation trên fixed dataset.

V3-003 PostgreSQL gate phải chạy migration trên database mới, kiểm tra partial unique index
`uq_extraction_results_accepted_cache`, read-after-write cho accepted cache, audit rows cho
`rejected/needs_review`, rollback không để lại half-result và savepoint re-read khi duplicate
accepted insert. Lệnh opt-in dùng database tạm:

```powershell
docker compose --env-file .env.example up database --wait
$env:DEVRADAR_TEST_DATABASE_URL = 'postgresql+psycopg://devradar:devradar_local_only@127.0.0.1:55432/postgres'
.venv\Scripts\python -m pytest tests/integration/test_extraction_result.py -m postgresql
Remove-Item Env:\DEVRADAR_TEST_DATABASE_URL
```

Nếu database không khả dụng, test phải báo `skipped` với lý do; không được ghi evidence như
integration pass.

PostgreSQL test hiện dùng `DEVRADAR_TEST_DATABASE_URL`, tạo database tên ngẫu nhiên rồi drop bằng `WITH (FORCE)`. Chỉ trỏ biến này tới local/CI role riêng có quyền tạo database tạm; không chạy với production credential.

### 4.3. End-to-end và acceptance

- V1: trigger approved adapter qua operator path, ingest dataset và query qua API.
- V2: nhiều scheduled fixture cycles phát hiện new/update/missing/removed/reactivated, duplicate slot không process lại, partial/anomaly không false removal và quarantine recovery đúng policy.
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
| Duplicate schedule/API trigger hoặc hai worker claim | Một trigger/pending row chỉ được process một lần; replay trả history hiện hữu. |
| Redirect/private address | Bị chặn và ghi safe policy error; không follow. |
| Empty/anomalous source response | Coverage không được coi complete nếu invariant chưa đạt. |
| HTML/JD malformed | Snapshot còn để replay; parser fail có taxonomy. |
| LLM malformed/hallucinated output | Schema/evidence gate reject hoặc bounded retry/review. |
| Taxonomy unknown/role ambiguous | Giữ evidence, trả `needs_review`; không auto-merge hoặc tự suy đoán. |
| Summary unsupported claim/extra field/control char | Candidate validator reject; không đưa vào canonical data hoặc log. |
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
- Outbound HTTP dùng source allow-list, resolve toàn bộ IP, reject mixed/private/reserved answer, connect tới numeric IP đã pin nhưng validate TLS theo hostname, revalidate redirect, timeout và size cap; production deployment vẫn cần egress control như lớp phòng thủ bổ sung.
- Browser crawler áp cùng scheme/host/IP policy cho navigation, iframe, subresource và WebSocket; dùng fresh ephemeral context, chặn service worker/download/popup/external protocol, không cấp camera/microphone/geolocation/clipboard/file access và không dùng persistent cookie/storage. V1 Compose tách browser vào opt-in `crawler` profile, chạy UID 999 với read-only filesystem, `no-new-privileges`, drop toàn bộ capability rồi chỉ add `SYS_CHROOT`, bật Chromium sandbox và pin official Playwright `1.62.0` seccomp profile. `init: true` và host IPC theo upstream recommendation cho Chromium local; không diễn giải application allow-list thành network-level egress enforcement.
- HTML hiển thị bằng framework escaping; không render raw source/model HTML.
- File upload kiểm tra extension, MIME và signature; bounded size/page/decompression; parser không thực thi macro/script và chạy với least privilege.
- Authenticated deployment dùng HTTPS, restricted CORS, security headers, secure/httpOnly/sameSite session cookie nếu chọn session strategy.
- Authorization kiểm tra owner/operator ở server trên mọi protected resource.
- V2 local write API chỉ nhận `sourceId` + custom idempotency header, enqueue DB và không nhận URL/outbound option; default-disabled gate cùng loopback Compose binding giảm accidental exposure nhưng không thay authentication.
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
| Data | `jobs_new_total`, `jobs_updated_total`, `jobs_missing_total`, `jobs_removed_total`, `jobs_reactivated_total`, `duplicates_candidate_total`, `parse_failures_total` |
| Source | `source_last_success_age`, `source_failure_rate`, `source_coverage_anomalies_total`, health state |
| AI | `ai_requests_total`, `ai_cache_hits_total`, extraction/classification/summary accepted/rejected/needs-review counts, provider attempts, `ai_validation_failures_total`, `ai_latency_seconds`, input/output tokens, estimated cost |
| Agent | `agent_runs_total`, decision/retry/review count, step-limit hit, failure rate |
| API | request count, latency, status code, validation/rate-limit failures |
| CV/alert | upload reject/cleanup, match duration, deletion completion, delivery success/duplicate prevented |

Metric label không chứa URL query, title/company tùy ý, raw skill, CV field, error text hoặc user-provided high-cardinality value.

### 7.3. Log levels và redaction

- `INFO`: state transition và aggregate result;
- `WARN`: degraded/anomaly/retry/review;
- `ERROR`: operation failed với error code và correlation ID;
- debug payload chỉ dùng fixture/sanitized local mode, tắt ở public deployment.

Redact authorization/cookie/token, database DSN credential, prompt/JD/CV content và provider response.
Extraction error chỉ được giữ `result_id`, input hash, version, status và bounded error code/path/type;
không serialize `output_data` đầy đủ hoặc rejected value. Không dựa vào redact regex duy nhất; ưu tiên
allow-list structured fields.

V1 hiện ghi JSON line ra stderr bằng standard library, không thêm telemetry dependency hoặc public metrics endpoint. Event surface được khóa như sau:

- `http_request_completed`: request ID, HTTP method, route template, status và duration; không ghi path parameter value, query, header hoặc body;
- `api_error`: request ID, status, safe error code và exception class; không ghi exception message/stack/SQL;
- `job_observation_processed`: run/source/snapshot/job ID, outcome và `transaction_state=caller_owned_uncommitted`; không được diễn giải event này thành commit thành công;
- `crawl_run_summary`: run/source ID, status, coverage, duration, bounded counters và safe error code; runner chỉ emit summary cuối sau transaction outcome rõ.

API request count/latency/status và run/job outcome được tính bằng cách aggregate event name + bounded numeric/enum field. Opaque correlation ID chỉ dùng trace lookup, không dùng làm metric label. Persisted run counters và source failure vẫn đọc qua `/api/v1/crawl-runs`; V1 chưa cần Prometheus client hoặc in-process metrics registry.

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

Command cụ thể trong README/AGENTS phải từng chạy thành công và được cập nhật khi toolchain đổi. CI không được “green” bằng cách skip silently một gate bắt buộc; live/optional test phải báo rõ trạng thái skipped và lý do.

## 11. Deployment gates

### Local V1–V4

- clean setup từ documented prerequisites;
- migration chạy trên PostgreSQL mới;
- một approved fixture/source run và API smoke;
- pending operator run được xử lý ngoài HTTP bằng one-shot worker; queue rỗng exit thành công, source mismatch fail trước network;
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
