# AI, embeddings và agentic workflow

## 1. Nguyên tắc

AI là lớp bổ sung có giới hạn, không phải nguồn sự thật hoặc orchestration mặc định.

1. **Deterministic-first:** structured data, parser và taxonomy rule chạy trước.
2. **Model output is untrusted:** parse, validate, bound và encode trước khi dùng.
3. **Evidence-backed:** field/insight/match explanation phải trỏ tới input hoặc aggregate query.
4. **Version everything:** input hash, schema, extractor, prompt, model, embedding và scoring version.
5. **Explicit provider boundary:** DeepSeek V4 Pro chỉ được `Accepted` cho synthetic generation spike; ADR-010 chấp nhận fixed-revision local multilingual MiniLM riêng cho embedding. Không suy luận capability từ OpenAI-compatible wire format hoặc tự fallback provider.
6. **Bounded agency:** model không tự chọn arbitrary URL, chạy shell/SQL, ghi database hoặc gửi alert.

## 2. Phase boundary

| Capability | Phase | Trạng thái trước phase |
|---|---|---|
| Deterministic extraction | V1 | Required |
| LLM structured extraction fallback | V3 | V3-003 boundary implemented; production provider chưa có |
| Job classification và bounded summary | V3 | V3-004 deterministic boundary implemented; evidence-validated |
| Skill taxonomy assisted mapping | V3 | V3-004 versioned deterministic map; unknown cần review |
| Embedding và pgvector | V3 | V3-005 local multilingual MiniLM 384d + exact pgvector implemented theo ADR-010; private/local |
| Planner/validator/analyst workflow | V4 | Planner/validator direct workflow implemented provider-neutral; analyst còn V4-005; LangGraph deferred theo ADR-012 |
| Resume extraction/matching | V5 | Proposed |
| LLM-written alert/explanation | V5 | Optional; deterministic evidence required |

Không thêm SDK/model dependency trong V1–V2 chỉ để chuẩn bị.

V3-002 đã `Accepted` cho synthetic generation spike với DeepSeek `deepseek-v4-pro` ở non-thinking JSON mode; held-out v6 đạt toàn bộ target sau deterministic canonicalization (schema/evidence, skill, level, salary, location `1.0`; experience và complete accepted `0.875`). Đây là contract-level result, không phải raw model-only accuracy cho scalar field. [ADR-010](decisions/0010-accept-fastembed-minilm-semantic-remediation.md) tách embedding sang local FastEmbed/multilingual MiniLM và exact pgvector; không gửi source JD/query/CV ra external embedding provider. Chưa có production DeepSeek provider adapter.

## 3. LLM extraction contract

LLM chỉ nhận phần text cần thiết cùng schema/version. Prompt phải nói rõ nội dung JD/CV là dữ liệu không đáng tin và không được làm thay đổi policy.

Output logic tối thiểu:

```json
{
  "schemaVersion": "job-extraction-v1",
  "role": "Backend Engineer",
  "levels": ["junior", "mid"],
  "requiredSkills": [
    {
      "name": "Python",
      "evidence": "experience in Python",
      "confidence": 0.98
    }
  ],
  "optionalSkills": [
    {
      "name": "Kafka",
      "evidence": "Kafka is a plus",
      "confidence": 0.95
    }
  ],
  "warnings": []
}
```

Schema thực tế phải giới hạn enum, collection size, string length và numeric range. Evidence span phải tồn tại trong canonical input sau normalization; nếu không tìm thấy, field không được auto-accept. Trước strict schema validation, deterministic canonicalizer áp dụng taxonomy alias cho skill và giữ `levels`, `experience`, `salary`, `location` theo parser hiện hành trên input canonical. Model không được override các scalar field này; field mơ hồ giữ `null`, salary raw vẫn được giữ riêng.

V3-003 lưu `ExtractionResult` trong PostgreSQL với `input_type=job`, `input_ref=Job.id`, `input_hash=Job.job_content_hash`, `extractor_version`, `schema_version`, `prompt_version`, `model` và `canonicalization_version`. `output_data` chỉ là `ExtractionPayload` đã validate; `validation_errors` chỉ có safe `code/path/type`. Deterministic-complete result được persist `rule/accepted` và không gọi provider. Provider boundary là callable được inject cho test/spike, không phải DeepSeek adapter production; request không có URL, credential, tool capability hoặc CV.

Extractor hiện hành là `deterministic-job-v2`: khi canonical `Job.levels` rỗng, chỉ dùng level marker rõ ràng trong title qua cùng `normalize_levels` rule; nếu không có evidence vẫn giữ rỗng và chuyển `needs_review`. Đây là fallback local có version riêng, không phải suy đoán từ số năm kinh nghiệm.

Job classification dùng taxonomy/version và trả evidence giống extraction field. AI summary phải ngắn, chỉ tổng hợp claim được hỗ trợ bởi canonical JD và bị reject nếu thêm salary, skill, benefit hoặc requirement không có evidence.

### 3.1. V3-004 taxonomy/classification/summary boundary

`job-taxonomy-v1`, `job-role-classification-v1` và `job-bounded-summary-v1` là version identity của boundary hiện tại. `TaxonomySkill` dùng lại alias map của deterministic extraction; category known có confidence `1`, unknown giữ `other` và chuyển `needs_review`. Requirement type không bị đổi khi map category.

Role classifier chỉ chấp nhận role family có marker deterministic. Marker trong title có trọng số cao hơn description; tie hoặc không có marker trả `needs_review`, không suy đoán role. `levels` luôn lấy từ canonical Job.

Bounded summary là một dòng tối đa 420 ký tự với tối đa 8 evidence claims. Builder không thêm claim ngoài role/skill/level evidence đã kiểm chứng. Candidate validator dùng `extra=forbid`, kiểm tra version, evidence substring, control character và yêu cầu text khớp renderer deterministic sinh từ role/skill evidence; mọi phần prose/claim thêm bị `rejected`. Không có summary provider hoặc DeepSeek call trong V3-004.

## 4. Validation và retry

Validation theo thứ tự:

1. response envelope và extraction object shape parse thành công;
2. deterministic canonicalization cho alias và field đã có parser;
3. schema/type/range validation;
4. evidence verification với input;
5. domain invariant và taxonomy mapping;
6. confidence/policy gate;
7. accept, reject hoặc `needs_review`.

Retry chỉ dành cho lỗi transient hoặc malformed structured output có khả năng sửa. Không retry vô hạn hoặc retry hallucination bằng cùng input/prompt mà không đổi chiến lược. V3-003 giới hạn đúng hai transient attempts; malformed shape/extra field/enum/evidence invalid bị `rejected` an toàn, provider thiếu hoặc transient exhausted là `needs_review`. Persistence re-check accepted cache sau provider call để xử lý concurrent writer; provider không chạy trong transaction giữ row lock. V4 direct workflow có đúng hai proposal attempts và bốn logical stages; policy/application rejection hoặc valid review không retry.

Validator agent không thể override source policy, invent evidence hoặc tự commit kết quả. Nó trả decision schema để deterministic application layer áp dụng.

## 5. Evaluation

### 5.1. Dataset

V3-001 đã khóa labeled dataset versioned gồm:

- JD Việt, Anh và mixed-language;
- required/optional skill;
- level và experience mơ hồ;
- salary/location edge case;
- malformed/short/noisy description;
- prompt-injection-like text;
- field không có trong source để đo hallucination.

Tách train/development examples khỏi held-out evaluation. Fixture không chứa secret/PII và phải giữ source/provenance hợp lệ.

Contract hiện hành là `job-extraction-eval-v1` / `job-extraction-eval-schema-v1`: 4 development case và 8 held-out case synthetic, project-authored. File/hash, coverage và baseline nằm tại [V3-001 evidence](evidence/V3-001-evaluation-dataset-and-baseline.md). Held-out không được đưa vào prompt few-shot hoặc dùng để tuning.

### 5.2. Metrics

- structured-output/schema success rate;
- exact/normalized accuracy theo field;
- classification accuracy và unsupported-claim rate của summary;
- precision, recall và F1 cho skill cùng requirement type;
- unsupported-field/hallucination rate;
- reject/needs-review rate;
- deterministic coverage và LLM fallback rate;
- latency p50/p95, token và estimated cost trên mỗi accepted result;
- regression theo language/source/parser/model version.

Không đặt accuracy/cost threshold chỉ dựa vào mong muốn. V3 entry spike tạo baseline; target release được ghi vào evaluation artifact và roadmap trước khi model output ảnh hưởng canonical data.

Baseline held-out `deterministic-keyword-v1`: skill F1 `0.9545`, unsupported skill `0.0455`, deterministic complete `0.6250`. Gate extraction V3 trên cùng dataset là skill F1 `>=0.9700`, unsupported skill/hallucination `0`, accepted schema/evidence `1.0` và complete accepted result `>=0.8750`; deterministic level/salary/location không được regression. Cost/latency baseline đã được đo trong V3-002. Role/summary contract đã có ở V3-004, còn aggregate accuracy/hallucination target phải được ghi cùng evaluation artifact trước khi provider output ảnh hưởng canonical data.

### 5.3. Release gate

- model/prompt/schema mới phải chạy cùng held-out suite;
- regression quan trọng chặn release hoặc cần documented waiver có review date;
- sample output đẹp không thay thế aggregate metric;
- provider fallback không được làm đổi schema/domain semantics;
- eval report ghi dataset version, model identifier, prompt version, parameters, date và environment.

## 6. Caching và reproducibility

V3-003 dùng accepted-only cache theo từng `input_ref`; rejected/needs-review không phải cache hit. Cache key đầy đủ gồm:

```text
input_type
+ input_ref
+ input_hash
+ extractor_type
+ extractor_version
+ schema_version
+ prompt_version
+ model
+ canonicalization_version
```

Job không đổi và key không đổi thì chỉ result `accepted` mới được reuse. Đổi input reference, content hash,
prompt/model/schema/extractor/canonicalization version tạo cache miss và extraction attempt mới; không
overwrite result cũ. PostgreSQL partial unique index giữ một accepted row cho một logical key, trong khi
rejected/needs-review rows vẫn được audit.

## 7. Embeddings và semantic search

- PostgreSQL vẫn là system of record; `job_embeddings` là derived data và pgvector được bật từ migration V3-005.
- Boundary hiện hành là `local_fastembed` + `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, artifact source `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`, revision `faf4aa4225822f3bc6376869cb1164e8e3feedd0`, mean pooling/normalization và dimension 384.
- Explicit download/build step chỉ lấy required artifact từ fixed revision và kiểm SHA-256; inference dùng local files only. Container đặt `ORT_DISABLE_TELEMETRY=1` trước runtime init để không tạo uploader/device identifier. Missing/corrupt artifact trả unavailable, không download trong request hoặc fallback external.
- Job input dùng `job-embedding-input-v2`, canonical title/description bounded 12.000 ký tự; query và passage được normalize, giới hạn lần lượt 300/12.000 ký tự và không thêm prefix vì model metadata ghi prefix không cần thiết.
- Embedding lưu input hash/schema, provider/model/revision, dimension, latency và created time. Không so sánh vector từ identity không tương thích; hash cũ không được coi current.
- Semantic API dùng exact cosine, áp Job status/source/skill filter trước rank và tie-break bằng Job ID; `relevanceScore` là similarity trong `[-1,1]`, không phải probability.
- CV embedding chỉ dùng `ResumeProfile` được phép xử lý từ V5; không reuse Job embedding boundary ngầm định.
- Xóa/expire ResumeProfile phải xóa hoặc vô hiệu embedding và match liên quan.
- Raw vector, model path và raw query/JD không được trả hoặc ghi log.
- Không thêm HNSW, Pinecone/Qdrant, Redis hoặc distributed embedding worker trước khi V3-006/V6 đo bottleneck thực tế.

## 8. Match score

Scoring là deterministic, versioned và giải thích được. Công thức từ ý tưởng chỉ là giả thuyết khởi đầu cho V5:

```text
overall =
    0.40 * skill_match
  + 0.25 * semantic_similarity
  + 0.15 * experience_match
  + 0.10 * location_match
  + 0.10 * level_match
```

Trước khi nhận là `scoringVersion=v1`, V5 phải:

- định nghĩa cách tính và missing/null behavior của từng component;
- tạo labeled/ranked examples;
- kiểm tra score range, monotonicity và edge case;
- công bố đây là ranking heuristic, không phải xác suất tuyển dụng;
- version weights và recompute/stale policy khi profile/job đổi.

LLM có thể diễn đạt explanation từ component/evidence đã tính. LLM không tự sinh overall score hoặc missing skill không có bằng chứng.

## 9. Agent responsibilities

V4 bắt đầu với ba responsibility có reasoning rõ ràng, không mặc định tạo sáu service/agent riêng.

### 9.1. Planner

Input: source health, last success, failure/change/new-job rates, schedule policy và budget.

Allowed output:

- priority trong enum/range đã định;
- đề xuất delay/retry/quarantine review;
- reason và metric references.

Không được thêm source/URL, đổi allow-list, vượt rate limit, override pause/quarantine hoặc tự chạy tool ngoài danh sách.

### 9.2. Validator

Input: raw reference, extraction result, validation errors và retry count.

Allowed output: `accept`, `reject`, `retry_with_strategy`, `needs_review`, kèm reason/evidence. Deterministic layer kiểm tra decision và giới hạn retry.

### 9.3. Analyst

Input V4-005 là `analyst-trend-evidence-v1` cho đúng một canonical skill: exact query window/filter/granularity/top-skill/version metadata và toàn bộ response bucket đã validate. Projection không copy float `coverage`/`share`; nó recompute integer basis points bằng half-up từ `denominator`, `analyzed_jobs` và `job_count`. Builder chỉ đưa first/last bucket, exact query/metric refs, deterministic `increased | decreased | unchanged` và exact `low_coverage` caveat vào `analyst-facts-v1`.

Output chỉ là typed `publish_insight | reject_claim | needs_review`. Publish phải khớp exact `skill_trend` claim, aggregate-query evidence, một supported metric, deterministic direction và expected caveat tuple. Analyst không tự query SQL, không nhận Session/query handle/tool, không viết prose và không dùng raw Job/JD/CV/HTML hoặc `ExtractionResult.output_data`.

### 9.4. Matcher, Trend và Alert

Ở V5, matching, trend calculation và alert eligibility trước hết là deterministic modules. Chỉ tạo agent riêng nếu evaluation chứng minh reasoning cải thiện kết quả có thể đo được. Text generation không tự biến module thành agent.

## 10. Agent/tool security

- Tool allow-list theo agent; default deny.
- Argument được schema-validate và authorization kiểm tra trong code, không dựa vào system prompt.
- Không tool shell, arbitrary SQL, arbitrary HTTP, secret access hoặc destructive database operation.
- Source/JD/CV text có thể chứa prompt injection; không đưa vào instruction channel.
- Model output không được render bằng raw HTML, dùng làm filename/path, SQL hoặc command.
- Step count, token, timeout, concurrency và cost có hard limit.
- Decision quan trọng có correlation ID và audit record nhưng redact PII/prompt content.
- Human/operator approval bắt buộc cho source policy change, external provider mới, retention mới hoặc alert channel mới chứa user data.

V4-001 đã cài internal `agent-decision-v1` và deterministic validation boundary trong module `agents`. Envelope dùng responsibility-specific enum/data, bounded opaque reference, finite confidence và reject extra field/reference ngoài input. Tool policy hiện chỉ authorize read-only `read_source_health`/`read_run_health`, `read_extraction_result`/`read_evidence_reference` hoặc `read_aggregate` theo đúng responsibility; không có executor cho shell, SQL, HTTP hoặc mutation.

Application context deterministic phải cấp explicit schedule permission, retry eligibility/cap/quarantine, validator accept gate và analyst denominator/query/metric support. Thiếu fact luôn fail closed. Boundary chỉ trả normalized action token; không có dynamic tool executor hoặc public API. Test/evidence nền tảng nằm tại [V4-001 deterministic agent policy](evidence/V4-001-deterministic-agent-policy.md).

[ADR-012](decisions/0012-accept-direct-v4-agent-workflow-defer-langgraph.md) chấp nhận direct bounded workflow sau isolated LangGraph `1.2.10` spike. Graph đạt same-process checkpoint recovery nhưng current responsibility chưa cần durable multi-step pause/resume/replay; V4 không thêm LangGraph/checkpointer/LangSmith dependency. V4-003 dùng typed run state + `AgentRun`; chỉ đánh giá lại graph runtime khi có measured durable-workflow need. [V4-002 evidence](evidence/V4-002-langgraph-direct-workflow-spike.md) ghi exact footprint, scenario, recovery và timing boundary.

### 10.1. V4 AgentRun safety boundary

Mỗi direct run dùng frozen `agent-run-limits-v1`; request, model output và environment variable không được override:

| Limit | Giá trị |
|---|---:|
| step | `4` |
| model attempt | `2` |
| tool call | `4` |
| latency | `180000 ms` |
| prompt + completion token | `8000` |
| estimated cost | `0.05000000 USD` |

Pure `agent-run-state-v1` kiểm usage delta trước khi nhận. Exact boundary được chấp nhận; increment vượt một đơn vị raise typed `limit_exceeded` và không truncate counter. Caller chuyển outcome đó thành `needs_review` bằng last accepted usage. Terminal state không nhận thêm usage/decision transition.

`AgentRun` chỉ audit opaque refs/hash/version, strict decision envelope, safe failure code (`timeout`, `provider_unavailable`, `invalid_output`, `limit_exceeded`, `ambiguous_input`, `internal_error`), bounded usage, correlation ID, model identity và timestamp. Database/log/error không giữ raw JD/CV/HTML, prompt/system message/chain-of-thought, free-form provider body, secret/header, vector hoặc arbitrary tool arguments. Persistence error cũng chỉ có allow-listed code/summary và không echo rejected input.

PostgreSQL khóa one-global-running slot, exact hard ceilings, terminal decision/failure invariants và one-direct-retry. Start/finalize chạy trong hai caller-owned transaction ngắn; proposal work nằm giữa hai transaction và ngoài row lock. V4-004 không mở AgentRun API, không auto-reset row `running` khi finalize fail và không thêm outer AgentRun retry.

### 10.2. V4-004 planner/validator proposal boundary

Deterministic builders tạo hai contract strict:

- `planner-facts-v1` chỉ chứa opaque Source/CrawlRun refs, approval/health status, safe reason code, bounded counters và schedule/retry permission đã tính từ persisted state;
- `validator-facts-v1` chỉ chứa opaque ExtractionResult/RawJobSnapshot refs, extractor/status, current hash/schema booleans, local schema/evidence booleans, safe `code/path/type` issues và bounded reparse permission.

Builder validator có thể đọc `ExtractionResult.output_data`, canonical Job text và RawJobSnapshot metadata nội bộ để kiểm schema/evidence/provenance, nhưng `agent-proposal-request-v1` không chứa `output_data`, raw JD/CV/HTML, URL, rejected value, prompt/provider body, secret, vector hoặc Session. Raw content được coi là untrusted data và không thể đổi policy/tool quyền.

Direct flow là `build → propose → validate → apply/fallback`. Proposal callable chỉ nhận request strict và trả candidate mapping cùng safe model/usage wrapper; nó không nhận database, URL, credential, logger hay mutation handle. Mỗi run tối đa hai proposal attempts, bốn logical stages và luôn `0` tool call. Candidate chỉ được persist sau `DecisionEnvelope` validation, responsibility/ref closure và `apply_decision()`:

- accepted non-review action → `succeeded`;
- deterministic application reject → `rejected` với validated decision;
- valid review → `needs_review` với validated decision;
- malformed/ref mismatch hoặc transient exhausted → `needs_review` với safe failure/fallback;
- unexpected execution error → `failed/internal_error`;
- usage overflow → `needs_review/limit_exceeded` bằng last accepted usage.

Transaction 1 commit row `running` trước proposal; proposal/validation/application chạy không Session; transaction 2 finalize terminal row. Finalize failure rollback transaction 2 và giữ row `running`/active slot để operator điều tra. Scripted callable chỉ chứng minh workflow correctness; V4-004 không có live model/provider, không gửi JD/CV ra ngoài và không tuyên bố usefulness cao hơn deterministic baseline. Test và boundary evidence nằm tại [V4-004 planner/validator workflow](evidence/V4-004-planner-validator-direct-workflow.md).

### 10.3. V4-005 analyst trend boundary

Current PostgreSQL analytics tiếp tục sở hữu query, cohort, denominator, coverage, bucket và top-skill ordering. Caller truyền cùng validated `SkillTrendQuery`/`SkillTrendResponse` vào deterministic projection; query/response meta mismatch, dưới hai bucket, bucket reorder/duplicate/outside window, missing/duplicate selected skill, unsafe version/skill hoặc arithmetic mismatch đều fail trước khi tạo `AgentRun`.

`aggregate_query_ref` hash exact window/filter/granularity/top-skills/version JSON. `trend_metric_ref` hash full query hash, canonical skill, two endpoint buckets, delta, direction và required caveat. `ApplicationContext` reconstruct exact expected claim/direction/caveat và chỉ support đúng metric ref; model không thể invent hoặc thay query, metric hay coverage caveat mà vẫn publish.

Analyst dùng nguyên direct flow `build → propose → validate → apply/fallback`, tối đa hai proposal attempts, bốn logical stages, `0` tools và hai transaction ngắn. Valid publish/reject/review, malformed/injection, timeout, limit, internal error, application reject và finalize failure đều giữ terminal/redaction semantics V4-004. Scripted proposal và PostgreSQL integration chỉ chứng minh contract/workflow correctness; V4-006 chịu trách nhiệm đo usefulness so với deterministic baseline và loại reasoning path nếu không cải thiện. [Evidence](evidence/V4-005-analyst-skill-trend.md).

## 11. Privacy và retention

- Chỉ gửi minimum necessary content tới external model.
- Không đưa API key, cookie, auth header, raw log hoặc dữ liệu user khác vào prompt.
- CV file gốc mặc định bị xóa sau parsing; raw text không nằm trong telemetry.
- External provider processing phải có config opt-in cho dữ liệu nhạy cảm và được nêu trong UI/docs trước public deployment.
- ResumeProfile, embedding, match và agent output phải hỗ trợ delete/expiry theo cùng owner scope.
- Dataset evaluation không dùng CV/JD chứa PII chưa được loại bỏ hoặc có quyền sử dụng không rõ.

## 12. Cost và failure handling

Mỗi task AI có budget theo request/run và metric: calls, attempts, tokens, latency, accepted/rejected,
needs-review, cache hit và estimated cost. Khi provider unavailable, rate-limited hoặc budget hết:

- ingestion deterministic vẫn tiếp tục;
- field AI-only giữ `null`/partial và lưu `needs_review` theo phase;
- không làm mất raw snapshot hoặc rollback canonical field đã xác nhận;
- không tự chuyển sang provider khác nếu chưa có adapter/evaluation tương đương;
- UI/API nêu rõ dữ liệu AI đang pending/degraded.

## 13. Acceptance scenarios

- Structured parser đủ schema: không có LLM call.
- Model trả malformed JSON, enum lạ hoặc evidence không tồn tại: reject/retry bounded.
- JD chứa “ignore previous instructions” hoặc URL/tool instruction: nội dung được coi là data, không có tool/action.
- Role marker không có hoặc bị tie: classification/summary là `needs_review`, không auto-claim.
- Summary evidence ngoài canonical input, extra field, control character hoặc claim salary/benefit/skill không được hỗ trợ: `rejected`.
- Provider timeout/rate limit: canonical ingestion vẫn thành công và trạng thái extraction rõ ràng.
- Cùng cache key: không gọi model lần hai.
- Đổi model/prompt/taxonomy: không reuse cache sai version.
- Model artifact thiếu/sai hash hoặc query vector sai dimension/non-finite: semantic request trả safe unavailable; không external fallback.
- Semantic query với status/source/skill filter: chỉ rank compatible current JobEmbedding trong cohort đã lọc.
- Skill frequency/trend khi extraction coverage thiếu: denominator vẫn là toàn Job cohort và response công bố `analyzedJobs`/coverage.
- CV raw text/embedding không xuất hiện trong log, error hoặc AgentRun response.
- Analyst claim không có denominator/query evidence: validation reject.
- Planner đề xuất host ngoài allow-list hoặc vượt policy: deterministic layer reject.
