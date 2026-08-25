# Operations, quality và security gates

## 1. Mục tiêu

Tài liệu này định nghĩa bằng chứng cần có để nói DevRadar chạy đúng, an toàn và có thể chẩn đoán. V1 data pipeline, V2 schedule/retry/lifecycle/health/operator queue và V3 extraction/taxonomy/local MiniLM/pgvector semantic boundary đã có verified evidence. V6-002 bổ sung session authentication/authorization; rate limit, security headers, managed secrets, deploy và backup vẫn là các gate V6 tiếp theo.

## 2. Environment

| Environment | Mục đích | Dữ liệu | Exposure |
|---|---|---|---|
| Local | Phát triển, fixture, source spike có kiểm soát | fixture và dữ liệu thật giới hạn | localhost/private |
| CI | Test, static analysis, migration/eval smoke | synthetic/fixture, không có PII | isolated |
| Demo | Portfolio demo từ V5 | dataset đã sanitize; CV ephemeral | protected hoặc read-only |
| Production-like | V6 public deployment | dữ liệu công khai + owner data có policy | HTTPS, auth, monitoring |

Kết quả kiểm tra capability máy phát triển trước V1 được ghi riêng tại [PRE-007 local prerequisites evidence](evidence/PRE-007-local-prerequisites.md); đây không phải Quick Start hoặc runtime proof của ứng dụng.

Scaffold, migration, safe fetch/snapshot, canonical persistence, API, observability và historical
source-specific adapter evidence được giữ trong `docs/evidence/`. Runtime hiện hành được xác minh riêng tại
[V6-020 Source Recipe evidence](evidence/V6-020-no-code-source-recipes.md); evidence cũ không có nghĩa adapter
cũ còn hoạt động. V3 model/vector/search/trend gates nằm tại [V3-005 evidence](evidence/V3-005-embeddings-search-trends.md)
và V6 auth runtime tại [V6-002 evidence](evidence/V6-002-authentication.md). Health endpoint chỉ chứng minh
API process sống; PostgreSQL, browser fallback và end-to-end recipe phải có gate riêng.

Không dùng production secret/data trong CI. Không gọi source/LLM thật từ default unit test; live integration phải opt-in, có budget và được gắn nhãn rõ.

## 3. Configuration và secrets

- Config được parse/validate một lần khi khởi động; thiếu secret bắt buộc phải fail closed.
- `.env.example` chỉ chứa key và placeholder, không chứa credential thật.
- `.env`, local override, key/certificate và exported data phải bị ignore khi scaffold Git.
- API key, database password, session secret, webhook token và source credential không được hardcode hoặc log.
- `DEVRADAR_OPERATOR_WRITE_ENABLED` mặc định `false`; đây chỉ là local deployment gate, không phải auth. Không bật write API trên public ingress trước V6 auth/authorization.
- `DEVRADAR_AUTH_ENABLED` mặc định `false` để giữ compatibility local. Khi bật, bắt buộc có
  `DEVRADAR_OPERATOR_PASSWORD_HASH` hợp lệ; tạo hash bằng `devradar.cli auth-hash-password` từ prompt,
  không truyền password qua command-line hoặc ghi hash vào log.
- `DEVRADAR_LOCAL_NO_LOGIN_ENABLED` mặc định `false`. Chỉ bật explicit cùng
  `LOCALHOST_SERVICE` + `DEVRADAR_AUTH_ENABLED=false`; API tạo/reuse `local-operator` trong PostgreSQL
  nhưng không tạo session/password/cookie. `PROTECTED`/`PUBLIC` hoặc auth + no-login fail startup;
  Origin/rate-limit/feature gate vẫn áp dụng cho local mutation.
- `DEVRADAR_SOURCE_RECIPES_LOCAL_ENABLED` mặc định `false` và chỉ hợp lệ với `LOCALHOST_SERVICE`.
  One-click launcher bật flag này cho process Compose; protected/public fail startup. Recipe không nhận
  credential, proxy, arbitrary header/script hoặc per-run URL.
- `DEVRADAR_AUTH_SESSION_TTL_SECONDS` phải nằm trong khoảng policy; `DEVRADAR_AUTH_COOKIE_SECURE=false`
  chỉ phù hợp loopback HTTP. Deployment HTTPS phải đặt `true`. `DEVRADAR_ALLOWED_ORIGINS` là allow-list
  cụ thể, không dùng wildcard với credential.
- `DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE` là default duy nhất cho local. `PROTECTED`/`PUBLIC`
  fail closed nếu auth tắt, cookie không Secure, origin wildcard, thiếu `DEVRADAR_SECRET_SOURCE=managed`
  hoặc DSN còn password local `devradar_local_only`. Secret manager thật và rotation drill vẫn cần do
  deployment V6-004 cung cấp; không giả vờ `.env.example` là managed secret.
- Rate limit process-local bật mặc định: general `120/60s`, login `10/900s`, dispatch `5/60s`, map tối đa
  `DEVRADAR_RATE_LIMIT_MAX_KEYS=10000`. Hết quota trả `429` + `Retry-After`; Redis/worker không được thêm
  chỉ để chia sẻ counter trước benchmark V6-006.
- Session cookie là HttpOnly và chỉ PostgreSQL hash được lưu. CSRF cookie có thể đọc ở browser để gửi
  `X-DevRadar-CSRF`; raw session/CSRF/password không được log, tracing, URL hoặc browser storage.
- `DEVRADAR_ALERTS_LOCAL_ENABLED` mặc định `false`; `DEVRADAR_DISCORD_WEBHOOK_URL`
  chỉ được đọc từ environment của local/protected deployment, phải là HTTPS
  Discord webhook allow-list và không được ghi vào DB/log.
- `DEVRADAR_EMBEDDING_MODEL_PATH` là optional local path, không phải model selector. Dù đổi path, application vẫn khóa model ID/revision/artifact hash theo ADR-010; request không được chọn path/model.
- External provider/source mới phải có owner, mục đích, data classification và rotation/revocation path.
- Nếu secret từng bị commit hoặc lộ trong log, rotate/revoke trước; chỉ xóa khỏi file không đủ.

## 4. Test strategy

### 4.1. Unit tests

Chạy nhanh, deterministic, không network:

- parser/normalizer cho text, URL, location, salary, level, experience và skill;
- identity, hash, idempotency, dedup và Job lifecycle;
- API schema/error/pagination helpers;
- PBKDF2 password/session hash, expiry/revocation, CSRF/origin và owner/operator authorization;
- match component/scoring version;
- AI output validator, evidence check, cost/step limit;
- V3 taxonomy/category, role ambiguity và bounded summary evidence/length validator;
- V3 canonical embedding input, model artifact integrity, query/vector bounds và safe model-unavailable behavior;
- redaction và security policy helpers.

### 4.2. Integration tests

- Source Recipe fixture → preview/mapping → RawJobSnapshot → normalized Job → PostgreSQL;
- safe fetch result → RawJobSnapshot trên PostgreSQL thật, gồm policy/config mismatch, invalid encoding và caller-owned transaction;
- rerun/reprocess và transaction rollback;
- migration up/down hoặc forward/rollback strategy phù hợp;
- FastAPI → PostgreSQL với OpenAPI/contract assertion;
- V2 scheduler/retry → run state/metrics;
- recipe preview/run request → `SKIP LOCKED` worker claim → ingestion/retry chain, không chạy network trong HTTP request;
- V3 pgvector extension/version/dimension/logical identity, idempotent backfill và exact query với current hash/model-version/status/source filters;
- V3 skill/trend denominator, extraction coverage, bounded window và stable ordering;
- V5 upload parser trong isolated test và owner access control;
- alert retry/idempotency với fake connector.

Test được gọi “PostgreSQL integration” chỉ khi thực sự chạy PostgreSQL, không phải SQLite/mock. Test AI live không được thay thế evaluation trên fixed dataset.

V5-003 có hai lớp kiểm chứng: parser unit fixture không chạm network/database và PostgreSQL API integration trên database tạm. V5-004 bổ sung pure scoring/evaluation, migration/model, generation và API integration trên PostgreSQL thật. Integration phải chứng minh migration round-trip/`alembic check`, active replay, expiry tombstone, cross-owner `404`, delete idempotent, default-disabled gate trước multipart parse, chunked total-body cap, decoded-PDF bomb/error mapping, parser-log sentinel, multipart negative cases, current/stale hash filtering, top-100/replay counts, model/profile invalidation và không có raw file/text/token/vector trong database/response/event.

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

- V6-020 local: create recipe → acknowledge notice → preview/map → enable → Crawl now → provenance/history.
- V2: nhiều scheduled fixture cycles phát hiện new/update/missing/removed/reactivated, duplicate slot không process lại, partial/anomaly không false removal và quarantine recovery đúng policy.
- V3: deterministic extraction + LLM fallback trên labeled suite; fixed local model backfill; keyword/semantic comparison và skill trend có denominator/coverage.
- V4: historical planner/validator/analyst safety suite và migration regression chứng minh runtime bị loại ở current head.
- V5: upload CV hợp lệ, xem match/evidence, xóa profile và xác nhận artifact hết hiệu lực.
- V6: public auth, authorization, rate limiting, backup restore và deploy rollback.

## 5. Scenario bắt buộc

| Scenario | Kết quả bắt buộc |
|---|---|
| Replay cùng snapshot | Không duplicate Job hoặc JobChange; metric idempotent. |
| Crawl network/parser fail | Run `partial/failed`; không tăng missing count. |
| Recipe chưa preview/current acknowledgement | Không enable hoặc enqueue; không outbound crawl. |
| Duplicate schedule/API trigger hoặc hai worker claim | Một trigger/pending row chỉ được process một lần; replay trả history hiện hữu. |
| Redirect/private address | Bị chặn và ghi safe policy error; không follow. |
| Empty/anomalous source response | Coverage không được coi complete nếu invariant chưa đạt. |
| HTML/JD malformed | Snapshot còn để replay; parser fail có taxonomy. |
| LLM malformed/hallucinated output | Schema/evidence gate reject hoặc bounded retry/review. |
| Taxonomy unknown/role ambiguous | Giữ evidence, trả `needs_review`; không auto-merge hoặc tự suy đoán. |
| Summary unsupported claim/extra field/control char | Candidate validator reject; không đưa vào canonical data hoặc log. |
| Model artifact thiếu/sai hash hoặc vector sai dimension/non-finite | Download/load/backfill/search fail closed bằng safe code; không external fallback hoặc persist vector lỗi. |
| Stale Job hash/model revision | Không reuse/rank embedding hoặc extraction không tương thích. |
| Analytics thiếu accepted extraction | Giữ Job trong denominator, giảm `analyzedJobs`/coverage; không bịa zero coverage thành full coverage. |
| Prompt injection trong JD/CV | Không đổi tool/policy, không gọi arbitrary action. |
| Upload sai type/magic/size | Reject, cleanup temporary file, không tạo profile dở dang. |
| Upload parser malformed/bomb | Request/file/page/decode/archive limit, cleanup và safe error; hard CPU timeout/process sandbox chưa có ở V5-003 local. |
| Owner khác đọc CV/match | Bị authorization chặn, không lộ resource existence theo policy. |
| JobMatch generation replay/stale | Current hash/version join; cùng identity không duplicate, Job đổi hash tạo row mới và row cũ invisible. |
| Missing/malformed extraction | Giữ Job trong denominator/available semantic, skill component `null` hoặc coverage giảm; không bịa skill. |
| Local model unavailable/invalid vector | POST trả `503`, không persist partial match; không download/fallback external. |
| Profile expire/delete giữa inference và persist | Generation trả generic `404`, không ghi row; cascade hoặc visibility predicate loại artifact. |
| Log/error/trace | Không chứa raw CV, secret, auth header, raw embedding hoặc full payload. |
| Alert retry | Không gửi trùng cùng idempotency key. |
| Alert webhook thiếu/sai cấu hình | Dispatch fail closed `503`, không tạo outbound request tùy ý và không lộ URL/token. |
| Alert rule của owner khác | Trả generic `404`; không trả rule, delivery hoặc profile existence. |
| Job content hash đổi | Tạo candidate delivery key mới; revision cũ không bị ghi đè hoặc gửi lại. |

## 6. Security baseline

### 6.1. Assets

- source/database/LLM/notification credentials;
- raw job evidence và dataset integrity;
- CV, ResumeProfile, embedding và match result;
- operator action, AI evaluation và audit trail;
- compute/budget cho crawler và model.

### 6.2. Controls theo trust boundary

- API input, third-party response và model output đều được schema-validate tại boundary.
- Database access parameterized; migration không chạy từ user input.
- Outbound HTTP dùng source allow-list, resolve toàn bộ IP, reject mixed/private/reserved answer, connect tới numeric IP đã pin nhưng validate TLS theo hostname, revalidate redirect, timeout và size cap; production deployment vẫn cần egress control như lớp phòng thủ bổ sung.
- Browser crawler áp cùng scheme/host/IP policy cho navigation, iframe, subresource và WebSocket; dùng fresh ephemeral context, chặn service worker/download/popup/external protocol, không cấp camera/microphone/geolocation/clipboard/file access và không dùng persistent cookie/storage. V1 Compose tách browser vào opt-in `crawler` profile, chạy UID 999 với read-only filesystem, `no-new-privileges`, drop toàn bộ capability rồi chỉ add `SYS_CHROOT`, bật Chromium sandbox và pin official Playwright `1.62.0` seccomp profile. `init: true` và host IPC theo upstream recommendation cho Chromium local; không diễn giải application allow-list thành network-level egress enforcement.
- HTML hiển thị bằng framework escaping; không render raw source/model HTML.
- File upload kiểm tra extension, MIME và signature; bounded size/page/decompression; parser không thực thi macro/script và chạy với least privilege.
- Authenticated deployment dùng HTTPS, restricted CORS, security headers và session cookie secure/HttpOnly/SameSite theo [ADR-015](decisions/0015-accept-v6-authentication-strategy.md); V6-002 phải cung cấp runtime evidence.
- API và Next.js BFF có baseline security headers; BFF có timeout 10 giây, request body 6 MiB và response
  2 MiB. CSP hiện là baseline có `unsafe-inline`/`unsafe-eval` để tương thích Next dev; strict nonce-based
  CSP và HSTS public rollout thuộc V6-004.
- Authorization kiểm tra owner/operator ở server trên mọi protected resource.
- V2 local write API chỉ nhận `sourceId` + custom idempotency header, enqueue DB và không nhận URL/outbound option; default-disabled gate cùng loopback Compose binding giảm accidental exposure nhưng không thay authentication.
- Error public generic; detail nội bộ được sanitize và correlation bằng request ID.
- LLM tool default deny, output không đi vào SQL/shell/path/HTML và có token/step/cost cap.
- Embedding artifact tải explicit từ fixed repository/revision, kiểm SHA-256 trước inference, chạy local-files-only và container disable ONNX Runtime telemetry trước initialization; query/JD/vector/model path không vào response/log và API không tự tải model.
- Dependency/lockfile được audit; finding chỉ được defer khi có reachability assessment, owner và review date.

### 6.3. Abuse cases cần test trước exposure

- attacker dùng source/run API để SSRF vào localhost/cloud metadata;
- source trả redirect qua host approved rồi tới private IP;
- JavaScript page dùng iframe/subresource/WebSocket để truy cập private host, tải file hoặc giữ state qua browser run;
- JD chứa prompt yêu cầu model tiết lộ secret hoặc gọi tool;
- file PDF/DOCX giả mạo, zip bomb hoặc parser exploit;
- anonymous user enumerate ResumeProfile/JobMatch;
- query/filter tạo SQL injection hoặc expensive unbounded query;
- alert rule gây spam/cost amplification;
- crafted model input gây prompt injection hoặc tăng token/cost ngoài budget.

## 7. Observability

### 7.1. Correlation

Mỗi request/crawl run/extraction/delivery có opaque ID. Log dùng structured fields và liên kết bằng ID/reference, không copy raw payload.

### 7.2. Metric tối thiểu

| Area | Metrics |
|---|---|
| Crawler | `crawl_runs_total`, `crawl_success_rate`, `crawl_duration_seconds`, `pages_fetched_total`, `response_bytes_total` |
| Data | `jobs_new_total`, `jobs_updated_total`, `jobs_missing_total`, `jobs_removed_total`, `jobs_reactivated_total`, `duplicates_candidate_total`, `parse_failures_total` |
| Source | `source_last_success_age`, `source_failure_rate`, `source_coverage_anomalies_total`, health state |
| AI | `ai_requests_total`, `ai_cache_hits_total`, extraction/classification/summary accepted/rejected/needs-review counts, provider attempts, embedding selected/created/cache-hit/stale counts, model unavailable, `ai_validation_failures_total`, `ai_latency_seconds`, input/output tokens, estimated cost |
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
- `resume_profile_processed`: profile ID, source format, extraction status và `created|reused`; không ghi filename, owner/content hash, skill/location, token hoặc raw CV.
- `alert_delivery_processed`: rule/job ID, channel, `sent|failed|duplicate_prevented`,
  attempt count và safe error code; không ghi idempotency key, webhook, title,
  company, URL hoặc message body.

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

V6-011 route unsuccessful push CI trên `main` qua owner-assigned GitHub issue. Workflow chỉ cấp
`contents: read` và `issues: write`, không checkout code/download artifact từ `workflow_run`, và payload
chỉ dùng run URL/ID, conclusion, SHA cùng event. `workflow_dispatch` tạo `[DRILL]` issue để kiểm tra route;
drill chỉ được đóng sau khi xác nhận author/assignee/body và lưu run/issue evidence. Route này không thay
thế public uptime alert vì chưa có HTTPS endpoint để monitor từ bên ngoài.

## 9. Retention, deletion và backup

Default được dùng cho đến khi có ADR thay đổi:

| Data | Default |
|---|---|
| Canonical Job, JobChange, Source, CrawlRun metadata | Giữ để phục vụ lịch sử; review khi dataset tăng. |
| Raw job payload | 90 ngày; hash/provenance metadata giữ lâu hơn để audit. |
| Application logs | 30 ngày ở deployment; local/CI ngắn hơn. |
| Agent/LLM audit metadata | 90 ngày; không giữ full prompt chứa raw content/PII. |
| JobEmbedding derived từ public Job | Giữ/rebuild theo canonical Job và model version; stale row không được query như current. |
| CV file gốc | Xóa ngay sau parsing thành công/thất bại cleanup. |
| ResumeProfile, profile embedding, JobMatch khi chưa có auth | Ephemeral, mặc định hết hạn sau 24 giờ. |
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
| V3 | fixed AI evaluation suite, fixed model integrity/inference smoke, pgvector migration/query integration, OpenAPI/search/analytics contract và cost/latency report |
| V4 | historical agent safety evaluation, explicit removal decision và `agent_runs` migration round-trip |
| V5 | frontend build, accessibility baseline, browser E2E, upload/delete/authorization tests |
| V6 | dependency/container scan, secret scan, auth/rate-limit/security header tests, deploy/rollback và restore drill |

Command cụ thể trong README/AGENTS phải từng chạy thành công và được cập nhật khi toolchain đổi. CI không được “green” bằng cách skip silently một gate bắt buộc; live/optional test phải báo rõ trạng thái skipped và lý do.

## 11. Deployment gates

### Local V1–V4

Product one-click path hiện hành trên Windows:

```powershell
.\start-devradar.cmd
```

Docker Desktop phải được cài đặt nhưng không cần chạy sẵn. Launcher kiểm tra `docker info`; nếu engine
chưa ready, nó tự mở Docker Desktop từ install location được hỗ trợ, không tạo process trùng và chờ tối đa
180 giây trước khi báo lỗi. Missing CLI/install location hoặc timeout đều trả exit code khác `0`; CMD giữ
cửa sổ mở để operator có thể đọc lỗi, mở thủ công Docker Desktop rồi chạy lại.

Sau preflight, launcher giữ `.env` nếu đã có, build API/web/crawler, migrate, bật localhost no-login +
Source Recipe worker, chạy API/web `/sources`/privacy smoke rồi mới mở dashboard. Nó không tự cài Docker,
auto-enable/auto-crawl recipe hoặc xóa volume. Manual Compose commands trong README/AGENTS là fallback.

- clean setup từ documented prerequisites;
- migration chạy trên PostgreSQL mới;
- một recipe fixture run và API smoke;
- pending preview/run được xử lý ngoài HTTP bằng recipe worker; queue rỗng exit thành công, config mismatch fail trước network;
- embedding download là explicit fixed-revision step; image/local artifact được kiểm integrity, bounded backfill idempotent và missing model cho safe `503` mà ingestion vẫn chạy;
- teardown không xóa volume/data nếu thiếu explicit operator action.

### Protected demo V5

- dataset license/policy và source attribution được review;
- CV feature local/protected hoặc có auth; no anonymous retention;
- HTTPS, secrets, CORS/security headers và resource limits;
- monitoring, budget limit và cleanup job hoạt động;
- demo claims khớp evidence hiện tại.

### V6-004 CI, deploy và rollback

`.github/workflows/ci.yml` là enforcement contract cho Python default/integration gates, web check,
Compose migration/API/web smoke và container advisory scan. Local command surface tương ứng là:

```powershell
.\scripts\migrate.ps1 -EnvironmentFile .env.example -Action check
.\scripts\deploy.ps1 -EnvironmentFile .env.example -ProjectName devradar -Image devradar-app:local -WebImage devradar-web:local -BaseUrl http://127.0.0.1:8000 -WebBaseUrl http://127.0.0.1:3000 -SkipBuild
.\scripts\rollback.ps1 -EnvironmentFile .env.example -ProjectName devradar -Image devradar-app:local -WebImage devradar-web:local -BaseUrl http://127.0.0.1:8000 -WebBaseUrl http://127.0.0.1:3000
```

Deploy order là Compose config → API/web image build/inspect → database healthy → `alembic upgrade head` →
API/web healthy → API + web/BFF smoke. `DEVRADAR_APP_IMAGE` và `DEVRADAR_WEB_IMAGE` cho phép rollback
hai application artifacts mà không đổi source. Rollback không chạy `alembic downgrade`; schema phải dùng expand/contract hoặc một
forward-compatible migration đã review. `-RequireHttps` bắt buộc với protected/public smoke và script
fail-closed nếu thiếu HTTPS cho một trong hai URL, authentication, Secure cookie, managed secret,
HTTPS CORS, operator password hash hoặc database password không còn giá trị local mặc định. Chi tiết
decision nằm tại [ADR-016](decisions/0016-accept-reproducible-ci-deploy-rollback.md) và [ADR-020](decisions/0020-accept-nextjs-standalone-web-compose-artifact.md).

Container advisory gate dùng Trivy image chính thức với digest pinned theo [ADR-019](decisions/0019-accept-pinned-trivy-container-gate.md),
scan riêng API, crawler, web và ingress image; database production vẫn phải được pin digest và kiểm tra image
identity trước deploy. Full HIGH/CRITICAL report phải được thu thập trước khi gate
`--ignore-unfixed`; nếu scanner/image/socket không chạy thì fail, không suy diễn an toàn từ image build.

V6-013 production foundation thêm [ADR-022](decisions/0022-accept-patched-caddy-scratch-ingress.md): official
Caddy/Traefik artifact không qua zero-fixable gate nên ingress được build từ pinned Caddy source, chạy
`FROM scratch` với user `10001:10001`, high ports `8080/8443`, `cap_drop: ALL` và không có shell/package
manager. Production env phải có `DEVRADAR_DATABASE_IMAGE` cùng digest bất biến với bốn application/release
images. Local route smoke không chứng minh public DNS/TLS/provider deployment.

Production workflow surface:

```powershell
# GitHub Actions workflow_dispatch only; release_sha phải là exact successful DevRadar CI SHA.
# Production environment variables: DEVRADAR_DOMAIN, DEVRADAR_HOST, DEVRADAR_SSH_USER,
# DEVRADAR_FIREWALL_ID.
# Production secrets: DEVRADAR_PRODUCTION_ENV_B64, DEVRADAR_SSH_PRIVATE_KEY,
# DEVRADAR_SSH_KNOWN_HOSTS, DIGITALOCEAN_TOKEN.
```

Workflow deploy dùng digest cho database/API/crawler/web/ingress, chỉ mở firewall SSH `/32` của runner
trong bounded window, ghi cleanup intent trước mutation và luôn xóa rule/temp credentials ở cleanup step.
Không paste credential vào command history, chat hoặc artifact; release manifest chỉ chứa SHA/run ID/digest.

GitHub `main` yêu cầu strict status checks theo đúng bảy job name trong workflow, linear history và
conversation resolution. Force-push và branch deletion bị chặn. Không yêu cầu approving review vì dự án
hiện là single-operator; `enforce_admins=false` giữ emergency owner bypass, nên mọi lần bypass phải có
commit/evidence và một run CI terminal tương ứng thay vì được xem là gate pass mặc định.

[ADR-023](decisions/0023-accept-encrypted-spaces-backup-and-uptime-boundary.md) bổ sung custom restic
`0.19.1` scratch artifact vào cùng container advisory gate. Production chỉ nhận HTTPS S3 repository và
GHCR image digest; local tag/repository chỉ được mở bằng explicit test switch. Password đi qua file mount,
Spaces key đi qua env file tạm và remote workflow logout GHCR/xóa credential/archive ở cleanup. Schedule
giữ `7 daily + 4 weekly`; đây là policy khởi đầu, chưa phải retention/RPO evidence cho tới khi chạy trên
Spaces thật. DigitalOcean Uptime workflow mặc định chỉ GET check/alert bằng token `uptime:read`.

### V6-005 backup, restore và monitoring

Backup dùng custom PostgreSQL archive và stream trực tiếp từ database container; archive nằm ngoài Git,
không in raw owner data hoặc credential. Restore mặc định vào database tạm, kiểm tra `alembic_version`
rồi drop; monitor phát JSON bounded event và fail khi health không `ok` hoặc latency vượt threshold.

```powershell
.\scripts\backup.ps1 -EnvironmentFile .env.local -ProjectName devradar -OutputPath backups\devradar-<timestamp>.dump
.\scripts\restore.ps1 -EnvironmentFile .env.local -ProjectName devradar -BackupPath backups\devradar-<timestamp>.dump
.\scripts\monitor.ps1 -BaseUrl https://devradar.example -RequireHttps -MaxLatencyMs 2000
```

ADR-017 giữ standard-library logger và command monitor; Prometheus/OpenTelemetry/monitoring SaaS chỉ được
thêm sau measured cardinality, retention, alert-routing hoặc latency need. Public closeout vẫn cần encrypted
off-host backup, schedule, retention, key rotation, RPO/RTO, restore timestamp và alert routing thật.

V6-014 đã thêm custom restic build/scan, local encrypted backup/check/retention/restore smoke, scheduled
production workflow và read-only Uptime verifier. Local smoke restore giữ source path dưới
`<target>/input/archive.dump`. Chưa có Spaces/Uptime credential nên chưa có provider backup/list/restore,
prune, rotation, RPO/RTO hoặc GET check/alert evidence; các gate đó vẫn mở.

### Public V6

- login/logout/me, missing/expired/revoked session, wrong credentials/role, cross-owner và legacy owner
  header rejection;
- CSRF missing/mismatch/origin, cookie attributes và same-origin BFF forwarding;
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
- local embedding artifact corruption, backfill failure hoặc semantic latency regression;
- secret exposure;
- CV/PII exposure hoặc deletion failure;
- bad deploy và rollback.

Mỗi incident record nêu impact, time range, affected data/source, containment, recovery evidence và follow-up owner; không đính kèm secret/PII vào ticket/log.
