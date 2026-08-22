# V4-004 — Planner/validator direct workflow

**Status:** `complete` ngày 2026-08-22. V4 vẫn `in_progress`; V4-005 analyst responsibility là task kế tiếp.

## Kết quả

V4-004 implement hai responsibility provider-neutral trên boundary V4-001/V4-003 mà không thêm model SDK, graph runtime, API, migration hoặc dependency:

- `planner-facts-v1` chuyển Source/CrawlRun persisted state thành opaque refs, safe status/reason/counter và schedule/retry permission đã tính deterministic;
- `validator-facts-v1` kiểm ExtractionResult/Job/RawJobSnapshot provenance, current hash/schema, local schema/evidence và chỉ phát safe `code/path/type` issue;
- `agent-proposal-request-v1` không nhận raw JD/CV/HTML, `output_data`, URL, rejected value, prompt/provider body, secret, vector, Session hoặc mutation handle;
- direct workflow chạy `build → propose → validate → apply/fallback`, tối đa hai proposal attempts, tối đa bốn logical stages và luôn `0` tool call;
- untrusted candidate phải qua strict `DecisionEnvelope`, responsibility/ref closure và existing `apply_decision()` trước khi có thể audit;
- executor commit `running` trong transaction 1, chạy proposal không Session/row lock, rồi finalize trong transaction 2;
- finalize failure rollback và giữ global active slot `running`; workflow không tự reset, bypass audit hoặc tạo outer retry row.

## Safe responsibility facts

Planner builder chỉ đọc identity, approval/health, safe reason, bounded counter và optional run state. `scheduled_action_allowed` chỉ true khi schedule due, source approved và không quarantined. Retry chỉ true cho failed/partial transient run dưới attempt cap 3, source approved và không quarantined. `KEEP_SCHEDULE`/retry proposal vẫn bị deterministic application reject nếu context không cho phép.

Validator builder đọc `output_data` và canonical Job text nội bộ để parse `ExtractionPayload`, kiểm unique skill key và evidence substring, rồi bỏ content. Accept chỉ được phép khi persisted status accepted, schema/hash current, local schema/evidence valid và không có validation issue. Retry strategy duy nhất là `deterministic_reparse`, chỉ dưới cap 3. Unsafe persisted issue/schema/reason bị đổi thành allow-listed builder error không echo rejected value.

Source/run/extraction/snapshot refs dùng UUID cùng bounded hash/version. Serialized facts/request tests xác nhận không có source URL/host/rate-limit payload, raw content, title/description, ExtractionResult output, provider body, secret hoặc tool argument.

## Direct workflow và terminal mapping

| Scenario | AgentRun status | Decision | Application/failure |
|---|---|---|---|
| Valid non-review action | `succeeded` | Validated | accepted action |
| Deterministic policy reject | `rejected` | Validated | safe rejection |
| Valid review action | `needs_review` | Validated | review; không retry |
| Malformed/injected/ref-mismatch sau 2 attempts | `needs_review` | Không | `invalid_output` |
| Timeout/provider unavailable sau 2 attempts | `needs_review` | Không | deterministic baseline + typed failure |
| Usage overflow | `needs_review` | Không | `limit_exceeded`, last accepted usage |
| Unexpected callable/application error | `failed` | Không | `internal_error` |

Valid application rejection và valid review dừng ngay sau attempt đầu. Malformed structured output hoặc typed transient failure mới được retry. Candidate/exception text không nằm trong evaluation/outcome/AgentRun. AgentRun limits vẫn cho tối đa bốn tool call ở contract dùng chung V4-003, nhưng V4-004 không có tool executor và workflow test/persistence luôn ghi `tool_call_count=0`.

Exact token/time/cost boundary `8000` / `180000 ms` / `0.05000000 USD` được accept. Overflow một đơn vị không nhận một phần delta; terminal fallback chỉ cộng safe logical step còn nằm trong cap. Hai malformed attempts vẫn là một proposal stage và một validation stage, nên total không vượt bốn step.

## Transaction và PostgreSQL evidence

Integration test dùng PostgreSQL fresh database/migration cho cả planner và validator:

1. builder tạo refs từ real Source/CrawlRun/Job/RawJobSnapshot/ExtractionResult rows;
2. proposal callable mở Session độc lập, đọc được row đã commit `running` với zero usage và active slot;
3. callable trả scripted candidate; workflow chạy ngoài transaction đầu;
4. transaction hai lưu exact status/decision/model/usage và release slot;
5. timeout/unexpected error vẫn finalize safe terminal row khi database available;
6. malformed/injection candidate không xuất hiện trong `decision_data`, `input_refs`, `limits_snapshot` hoặc safe outcome;
7. forced finalize exception rollback transaction hai, để nguyên zero-usage `running` row và second start fail `concurrent_run`.

`AgentExecutionOutcome` có đúng run ID, responsibility, terminal status, validated application result và optional safe failure code. Nó không trả candidate, facts, model body, usage detail hoặc raw input.

## RED → GREEN

TDD RED đã được quan sát trước từng production slice:

```text
Application schedule gate:
2 failed, 8 passed
scheduled_action_allowed bị extra_forbidden và field contract chưa tồn tại

Responsibility builders:
ModuleNotFoundError: No module named 'devradar.agents.responsibilities'

Unsafe schema-version regression:
1 failed
DecisionRef ValidationError echo injected rejected value trước safe pre-validation

Pure workflow:
ModuleNotFoundError: No module named 'devradar.agents.workflow'

PostgreSQL executor:
ImportError: cannot import name 'AgentExecutionOutcome'
```

GREEN checkpoints:

```text
Application gate: 10 passed
Responsibility + application: 34 passed
Workflow + application + run state: 43 passed
All V4-004 targeted unit: 67 passed
Workflow + AgentRun PostgreSQL targeted: 26 passed
```

## Verification đã chạy

Chạy trên Windows PowerShell, Python 3.13.14 và PostgreSQL 18 local:

| Gate | Kết quả |
|---|---|
| V4-004 targeted unit | `67 passed` |
| V4-004/AgentRun PostgreSQL targeted | `26 passed` |
| Default pytest | `272 passed, 53 skipped` |
| PostgreSQL full pytest | `325 passed` |
| Alembic upgrade/check | `No new upgrade operations detected` |
| Docker Compose crawler profile config | Pass |
| Ruff check | Pass |
| Ruff format | `180 files already formatted` |
| mypy strict | `Success: no issues found in 93 source files` |
| pip check | `No broken requirements found` |
| Markdown internal links | `78 files`, `0 invalid` |
| Dependency diff | `.in`/locks không đổi |
| Migration diff | Không có migration/schema change |

`53 skipped` ở default là PostgreSQL opt-in cases; full PostgreSQL run phía trên chạy toàn bộ `325` test. Security scan hit raw/prompt/secret tokens chỉ ở local validation reads, persistence field names hiện hữu và negative test fixtures/assertions; proposal/audit serialization không có các value bị inject.

## Boundary chưa triển khai

- không có live DeepSeek/OpenAI/local model adapter, prompt template, API key/config hoặc model network call;
- không gửi real JD/CV/raw HTML/ExtractionResult output ra external processor;
- scripted callable chỉ chứng minh workflow correctness, không chứng minh reasoning usefulness/accuracy;
- analyst aggregate responsibility thuộc V4-005;
- comparison với deterministic baseline và quyết định giữ/loại agent thuộc V4-006;
- không có dynamic tool executor, domain mutation, public AgentRun API, worker/queue, cancellation hoặc stale-run recovery;
- LangGraph/checkpointer tiếp tục deferred theo ADR-012.

Vì vậy evidence này đóng V4-004, không đóng V4 và không tuyên bố production AI/provider runtime tồn tại.
