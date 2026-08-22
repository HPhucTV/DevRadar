# V4-004 Planner/Validator Direct Workflow — Design Spec

**Ngày:** 2026-08-22
**Trạng thái:** Đã được user xác nhận qua ba design section
**Phase:** V4 — Agentic decision layer

## Mục tiêu

V4-004 implement direct bounded workflow cho hai responsibility `planner` và `validator` trên boundary V4-001/V4-003. Workflow nhận safe deterministic facts, gọi một provider-neutral proposal callable, validate `agent-decision-v1`, áp dụng policy bằng `apply_decision()` và audit kết quả bằng `AgentRun`.

Task chứng minh workflow/policy/transaction correctness bằng scripted proposal callable. Nó không mở live provider, không gửi JD/CV ra ngoài, không thêm prompt/SDK/dependency và không dùng scripted output để tuyên bố AI cải thiện baseline.

## Các hướng đã cân nhắc

### 1. Provider-neutral direct workflow

Typed builders tạo safe facts; một injected callable trả candidate mapping cùng bounded usage metadata. Workflow thực hiện retry/validation/application/audit; tests dùng scripted callable, không network.

Accepted. Đây là thay đổi nhỏ nhất đáp ứng V4-004 trong khi ADR-008 chỉ cho DeepSeek synthetic generation và source approval chưa cho gửi real JD/CV tới external LLM.

### 2. Mở DeepSeek live trong V4-004

Cho phép đo latency/cost/model behavior thật nhưng cần privacy/evaluation gate và ADR mới. Planner chỉ có thể gửi non-sensitive derived metrics; validator vẫn không được gửi real source content. Scope sẽ trộn provider approval với responsibility workflow.

Rejected cho V4-004. Live provider/usefulness gate thuộc task riêng trước hoặc trong V4-006.

### 3. Deterministic-only responsibility functions

Không có proposal boundary, chỉ map facts trực tiếp sang action. Surface nhỏ nhất nhưng không kiểm chứng được untrusted proposal, attempt, usage hoặc fallback contract và gần như lặp V2/V3 baseline.

Rejected. Scripted provider-neutral seam cần thiết để test direct agent workflow mà không cấp external network.

## Decision và ADR boundary

- Tiếp tục ADR-012: direct workflow, không LangGraph/checkpointer/LangSmith.
- Giữ ADR-008: DeepSeek chỉ synthetic generation spike; V4-004 không đổi provider permission.
- Không cần ADR mới vì không thêm dependency, provider, database, network topology, public API hoặc quyết định khó đảo ngược.
- Nếu task sau thêm live provider hoặc gửi category dữ liệu mới, phải có evaluation/privacy/latency/cost gate và ADR mới trước implementation.

## Module boundary

### `agents.responsibilities`

Sở hữu strict safe-fact models và deterministic builders cho planner/validator. Builder được phép đọc ORM rows/policy facts nhưng không gọi model, không persist AgentRun và không mutate domain state.

### `agents.workflow`

Sở hữu direct four-stage execution, proposal attempt loop, usage accounting, `DecisionEnvelope` validation, `apply_decision()`/fallback mapping và two-transaction AgentRun lifecycle.

Không tạo repository/interface/factory. Proposal seam là một `Callable` type alias vì nó là trust boundary cần injection cho tests và future approved provider adapter. SQLAlchemy `sessionmaker` là transaction factory native; không bọc thêm database abstraction.

Không sửa `agents.decisions`, trừ khi implementation phát hiện contract đã duyệt không thể biểu diễn exact outcome. `agents.application` chỉ được mở rộng bằng deterministic policy fact thực sự cần để chặn planner action; không chuyển policy sang workflow hoặc proposal callable.

## Responsibility input contracts

Mọi model dùng strict frozen Pydantic convention hiện có: camelCase serialization, `extra=forbid`, bounded string/list, enum và finite/non-negative number. Fact payload không nhận arbitrary dictionary.

### Planner facts `planner-facts-v1`

| Field | Nguồn authoritative |
|---|---|
| `source_ref` | Persisted `Source.id`, kind `source` |
| nullable `crawl_run_ref` | Persisted latest/relevant `CrawlRun.id`, kind `crawl_run` |
| `approval_status`, `health_status` | Persisted Source enum |
| nullable `health_reason_code` | Safe bounded persisted reason code |
| `consecutive_failures`, nullable `baseline_items_found` | Persisted non-negative Source metrics |
| nullable latest `run_status`, `coverage_status`, `run_error_code` | Persisted CrawlRun safe state |
| `schedule_due`, `scheduled_action_allowed` | Deterministic V2 scheduler/policy facts, never model output |
| `retry_eligible`, `retry_attempt_number` | Deterministic V2 transient/cap policy |

Planner input refs gồm đúng Source và optional matching CrawlRun. Builder reject missing/mismatched row, unsafe reason/error code, negative counter, run khác source hoặc policy facts mâu thuẫn persisted approval/quarantine state.

`scheduled_action_allowed` chỉ true khi approval/pause/quarantine và scheduler policy cho phép. V4-004 thêm fact tương ứng vào `ApplicationContext`; `KEEP_SCHEDULE` bị deterministic application reject khi false. `DEFER` và `REQUEST_QUARANTINE_REVIEW` chỉ là recommendation; chúng không mutate schedule/quarantine. Existing retry gate vẫn yêu cầu `retry_eligible`, source không quarantined và CrawlRun attempt dưới cap 3.

### Validator facts `validator-facts-v1`

| Field | Nguồn authoritative |
|---|---|
| `extraction_result_ref` | Persisted `ExtractionResult.id`, kind `extraction_result` |
| nullable `raw_snapshot_ref` | Matching current `RawJobSnapshot.id`, kind `raw_snapshot`; chỉ opaque ref |
| `extractor_type`, `validation_status` | Persisted enum |
| `schema_version_current`, `input_hash_current` | Deterministic comparison với current contract/Job |
| `schema_valid`, `evidence_valid` | Deterministic local validation result |
| `validation_issues` | Bounded `code/path/type` only, không rejected value |
| `retry_eligible`, `retry_attempt_number` | Deterministic validation/retry policy |
| `allowed_retry_strategies` | Exact allow-list; V4 chỉ có `deterministic_reparse` |

Builder có thể đọc `output_data`/current Job/RawSnapshot nội bộ để tính booleans nhưng không đưa `output_data`, raw content, evidence text hoặc rejected value vào facts/callable/log. `validator_accept_allowed` chỉ true khi current hash/schema, local schema/evidence validation và persisted status đều cho phép. Retry vẫn do `ApplicationContext.allowed_retry_strategies` cùng attempt cap kiểm soát.

## Proposal boundary

`ProposalRequest` là strict union theo responsibility:

- schema version `agent-proposal-request-v1`;
- responsibility;
- exact input refs;
- `PlannerFacts` hoặc `ValidatorFacts` cùng responsibility;
- attempt number `1..2`.

Proposal callable nhận duy nhất `ProposalRequest`, không nhận Session, ORM object, logger, URL, secret, tool executor hoặc mutation handle.

Mỗi call trả `ProposalAttempt`:

- raw candidate mapping chưa được tin cậy;
- bounded safe model identity;
- non-negative prompt/completion tokens;
- estimated cost có tối đa 8 decimal places;
- không trả prompt, provider body, chain-of-thought, tool calls hoặc arbitrary metadata.

Workflow tự đo elapsed latency bằng monotonic clock. Candidate mapping chỉ được dùng làm input cho `DecisionEnvelope.model_validate()`; không persist/log trước validation. Tool calls không tồn tại trong request/response contract và `tool_call_count=0` cho toàn V4-004.

Scripted callable là test fixture, không phải production provider adapter và không được export như provider implementation.

## Direct workflow và usage

Một execution có tối đa bốn logical stage:

1. `build`: safe facts/input refs đã được deterministic builder tạo; final usage ghi `step_count=1` cho stage này;
2. `propose`: tối đa hai model attempts trong cùng AgentRun;
3. `validate`: parse `DecisionEnvelope`, kiểm responsibility/input-ref closure;
4. `apply/fallback`: gọi `apply_decision()` hoặc `fallback_for_failure()`.

Hai proposal attempts vẫn là một logical stage nhưng `model_attempt_count` tăng từng call. Retry chỉ xảy ra cho typed transient proposal failure hoặc malformed structured candidate khi còn attempt/time/token/cost budget. Policy/application rejection, decision mismatch, limit exceeded hoặc valid `needs_review` decision không retry.

Workflow duy trì local immutable `AgentRunState` và chỉ cộng accepted usage delta. Nếu một attempted delta vượt limit, state không truncate/nhận delta; run finalize `needs_review/limit_exceeded` bằng last accepted usage. Tổng limit tiếp tục là V4-003: 4 step, 2 model attempt, 0/4 tool call, 180000 ms, 8000 token và 0.05000000 USD.

## Transaction và data flow

1. Deterministic builder hoàn thành trước AgentRun start. Builder failure không tạo audit row vì chưa có valid bounded input identity.
2. Workflow mở Session/transaction ngắn, gọi `start_agent_run()` và commit `running`.
3. Proposal attempts, timing, schema validation và application chạy ngoài database transaction.
4. Workflow mở Session/transaction mới, lock/finalize đúng AgentRun bằng `finalize_agent_run()`.
5. `AgentExecutionOutcome` chỉ trả run ID, responsibility, terminal status, validated application result và safe failure code; không trả candidate/raw facts.

Persistence functions vẫn không commit/rollback. Workflow sở hữu transaction contexts qua native `sessionmaker`. Không giữ Session/row lock qua proposal callable.

V4-004 không auto-create outer AgentRun retry row. V4-003 retry relation dành cho explicit future/operator retry; model retry trong một execution chỉ tăng `model_attempt_count`.

## Terminal mapping

| Outcome | AgentRun status | Decision persisted | Safe failure |
|---|---|---|---|
| Application accepted action khác `REVIEW` | `succeeded` | Có | Không |
| Application deterministic reject | `rejected` | Có | Không |
| Valid decision dẫn tới `REVIEW` | `needs_review` | Có | optional `ambiguous_input` khi applicable |
| Malformed/invalid candidate sau bounded retry | `needs_review` | Không | `invalid_output` |
| Proposal timeout/unavailable | `needs_review` + deterministic baseline outcome | Không | `timeout` hoặc `provider_unavailable` |
| Usage limit exceeded | `needs_review` | Chỉ nếu decision đã validate trước limit sau đó | `limit_exceeded` |
| Unexpected internal execution error | `failed` | Không | `internal_error` |

Nếu second transaction/finalize fail, transaction rollback và row giữ `running`; workflow không tự reset/bypass active slot. Error ra caller chỉ có safe typed code. Operator investigation/stale recovery vẫn ngoài scope.

## Security và trust boundaries

- Source/JD/CV/RawSnapshot/ExtractionResult content là untrusted data; chỉ derived safe facts và opaque refs qua proposal boundary.
- Provider candidate là untrusted mapping; strict schema/application validation trước audit/action.
- Prompt injection string trong persisted content không thể xuất hiện trong ProposalRequest vì builders không copy content.
- Proposal callable không có tool/network/database capability từ workflow; V4-001 allow-list vẫn là policy contract nhưng V4-004 không implement dynamic tool executor.
- No raw facts/candidate/prompt/error body trong log hoặc AgentRun; chỉ run ID, responsibility, terminal status, safe code và bounded usage.
- Correlation/model/ref/version fields giữ pattern/length hiện có; validation error không echo rejected value.
- Không domain mutation. Planner/validator trả normalized recommendation/action token; existing deterministic application use case mới có thể sở hữu mutation ở task được phê duyệt sau.

## Testing

### Unit/TDD

- planner/validator facts reject extra field, raw content, `output_data`, prompt/tool/URL/secret field, unsafe error code và mismatched ref;
- planner builder reject run khác source, non-approved/quarantined contradiction và false retry/schedule permission;
- validator builder không serialize `output_data`/raw snapshot/rejected value và fail closed khi hash/schema/evidence không current;
- planner `KEEP_SCHEDULE`/retry không vượt deterministic policy;
- validator accept/retry không vượt local schema/evidence/strategy/attempt gate;
- scripted valid, application-rejected, valid-review, malformed-twice, transient-twice, timeout, injection-candidate và internal-error scenarios;
- exact 2 model attempts, 4 stages, 0 tool call; each token/time/cost boundary accepted và one-unit overflow becomes `needs_review/limit_exceeded`;
- candidate responsibility/ref mismatch không persist như valid decision;
- safe exception/outcome/log serialization không echo injected raw/secret strings.

### PostgreSQL integration

- real source/run/extraction/snapshot rows tạo đúng facts/ref provenance;
- first transaction persists `running` before scripted callable and closes Session;
- second transaction stores exact terminal mapping/usage and releases active slot;
- proposal callable exception vẫn finalizes safe terminal outcome khi database available;
- finalize rollback/error leaves one stuck `running` row and blocks second start;
- no raw/prompt/output field appears in AgentRun JSONB or structured log event;
- default tests không chạm PostgreSQL/network; opt-in suite dùng `DEVRADAR_TEST_DATABASE_URL`.

## Documentation trong implementation

- `docs/AI.md`: provider-neutral responsibility facts, attempt/fallback boundary;
- `docs/ARCHITECTURE.md`: direct workflow and transaction ownership;
- `docs/DOMAIN_MODEL.md`: không thêm entity; chỉ làm rõ AgentRun V4-004 usage nếu contract thay đổi;
- `docs/ROADMAP.md` và local board: V4-004 Done/V4-005 Ready chỉ sau unit + PostgreSQL evidence;
- `docs/evidence/V4-004-planner-validator-direct-workflow.md`: RED→GREEN, safe facts, failure mapping, full gates và untested provider/usefulness boundary.

Không đổi `docs/API.md` vì không có endpoint.

## Non-goals

- live DeepSeek/OpenAI/local model call, prompt template, API key/config hoặc provider adapter;
- gửi real JD/CV/raw HTML/ExtractionResult output ra external service;
- analyst responsibility, thuộc V4-005;
- AgentRun API, CLI command, scheduler integration hoặc background worker;
- dynamic tool executor, arbitrary SQL/HTTP/shell hoặc mutation capability;
- new migration/table/index, LangGraph/checkpointer, queue hoặc dependency;
- domain mutation, outer AgentRun auto-retry, cancellation hoặc stale-run recovery;
- usefulness/accuracy claim so với deterministic baseline, thuộc V4-006.

## Definition of Done

- strict planner/validator facts chỉ chứa approved safe fields/refs và fail closed ở mọi mismatch;
- direct workflow chạy đúng four-stage/two-attempt/zero-tool boundary và luôn qua V4-001 application policy;
- AgentRun two-transaction lifecycle/status/usage/failure mapping có PostgreSQL evidence;
- timeout/malformed/injection/limit/internal/finalize failure không lộ raw/secret hoặc mutate domain;
- `.in`/locks không đổi, không provider/graph/API/migration;
- full default/PostgreSQL/static/migration/Markdown gates pass;
- V4-004 Done, V4-005 Ready, V4 vẫn `in_progress`;
- evidence nêu rõ scripted proposal chỉ chứng minh workflow correctness, không chứng minh model usefulness.

## Tự kiểm tra spec

Spec giữ đúng hai source module, một callable seam và không tạo abstraction/infrastructure tương lai. Responsibility facts, attempt/step semantics, terminal mapping, transaction ownership và retry boundary có một nghĩa duy nhất. Mọi capability V4-004 được test; provider, analyst, mutation và usefulness được defer rõ. Không có placeholder hoặc dependency/ADR ngoài phase gate hiện hành.
