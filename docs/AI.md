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
| Planner/validator/analyst workflow | V4 | Evaluated rồi removed theo ADR-013 vì không có measurable usefulness gain; không có current agent runtime |
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

Retry chỉ dành cho lỗi transient hoặc malformed structured output có khả năng sửa. Không retry vô hạn hoặc retry hallucination bằng cùng input/prompt mà không đổi chiến lược. V3-003 giới hạn đúng hai transient attempts; malformed shape/extra field/enum/evidence invalid bị `rejected` an toàn, provider thiếu hoặc transient exhausted là `needs_review`. Persistence re-check accepted cache sau provider call để xử lý concurrent writer; provider không chạy trong transaction giữ row lock. Không có V4 agent proposal retry hiện hành.

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
- Raw vector, model path và raw query/JD không được trả hoặc ghi log. Local embedding boundary đặt `ORT_DISABLE_TELEMETRY=1` trước model load cả trong Docker và local venv.
- Không thêm HNSW, Pinecone/Qdrant, Redis hoặc distributed embedding worker trước khi V3-006/V6 đo bottleneck thực tế.

## 8. Match score

Scoring V5-004 là deterministic, versioned và giải thích được. Contract đã được khóa bằng synthetic development/held-out evaluation:

```text
overall =
    0.40 * skill_match
  + 0.25 * semantic_similarity
  + 0.15 * experience_match
  + 0.10 * location_match
  + 0.10 * role_match
```

`scoringVersion=job-match-scoring-v2` dùng `role` thay cho `level` vì ResumeProfile chưa có level/preference evidence đáng tin cậy. Component vắng mặt đóng góp `0` và không renormalize; `evidenceCoverage` là tổng weight có evidence. Skill component dùng tỷ lệ requirement `required:preferred:optional|mentioned = 3:2:1`; một required match trên cặp required+preferred là `0.6000`. Mỗi component/score làm tròn half-up bốn chữ số, score nằm trong `[0,1]`, tie-break là `score desc, job id asc`; explanation chỉ là token deterministic bounded. Chi tiết dataset/hash/gate nằm trong [V5-004 evaluation evidence](evidence/V5-004-scoring-evaluation.md). V2 invalidates row cũ sau khi requirement weights được sửa; profile embedding input cũng đã tăng lên `resume-match-embedding-input-v2` sau khi canonical order được sửa.

Trước khi mở scoring version mới, V5 phải:

- tạo dataset/schema/hash evaluation mới;
- kiểm tra score range, monotonicity, missing behavior, evidence closure và edge case;
- version weights và stale/recompute policy khi profile/job đổi;
- công bố đây là ranking heuristic, không phải xác suất tuyển dụng.

V5-004 không gọi LLM cho scoring/explanation. LLM không tự sinh overall score hoặc missing skill không có bằng chứng; CV chỉ được biến thành structured profile local và vector tạm trong memory, không lưu resume vector hoặc gửi external provider.

## 9. V4 agent evaluation outcome

V4 đã đánh giá ba responsibility `planner`, `validator` và `analyst` bằng typed, provider-neutral proposal boundary. Scripted callable chứng minh schema/policy/failure safety, nhưng comparison V4-006 cho thấy không responsibility nào có measurable usefulness gain:

| Responsibility | Deterministic outcome đã có | Vì sao reasoning không được giữ |
|---|---|---|
| `planner` | V2 schedule, retry cap, health và quarantine permission | Không có labeled priority/delay outcome; proposal chỉ chọn từ permission đã tính |
| `validator` | V3 schema/evidence/canonicalization và retry eligibility | Proposal không nhận evidence mới; accept/reject/retry đã được xác định |
| `analyst` | V3 aggregate cùng exact direction/caveat projection | Claim/query/metric/direction/caveat hợp lệ đều đã deterministic |

[ADR-013](decisions/0013-remove-unretained-v4-agent-runtime.md) loại cả ba reasoning path, package `agents` và `AgentRun` schema. Không có current agent runtime, tool registry, proposal loop, provider adapter hoặc model call. LangGraph vẫn bị defer theo [ADR-012](decisions/0012-accept-direct-v4-agent-workflow-defer-langgraph.md).

V4-001–V4-005 được giữ làm historical safety/evaluation evidence, không phải claim capability đang chạy. V5 matching, trend calculation và alert eligibility trước hết là deterministic modules; text generation không tự biến module thành agent.

## 10. Gate nếu đánh giá agent lại

Future reasoning path chỉ được mở khi có:

- responsibility không thể suy ra output trực tiếp từ deterministic input facts;
- frozen labeled dataset và metric usefulness/accuracy có baseline trước model run;
- no-regression gate cho schema, evidence, policy, privacy, latency và cost;
- default-deny tool policy; không shell, arbitrary SQL/HTTP, secret access hoặc destructive database operation;
- schema validation/authorization trong code, hard step/token/timeout/cost limits và deterministic fallback;
- external-provider/privacy ADR trước khi gửi bất kỳ content nào;
- audit redaction không giữ raw JD/CV/HTML, full prompt, chain-of-thought, secret, vector hoặc provider body.

Source/JD/CV text luôn là untrusted data và không được đổi instruction, allow-list hoặc action. Human/operator approval vẫn bắt buộc cho source policy, provider, retention hoặc alert channel mới chứa user data.

## 11. Privacy và retention

- Chỉ gửi minimum necessary content tới external model.
- Không đưa API key, cookie, auth header, raw log hoặc dữ liệu user khác vào prompt.
- CV file gốc mặc định bị xóa sau parsing; raw text không nằm trong telemetry.
- External provider processing phải có config opt-in cho dữ liệu nhạy cảm và được nêu trong UI/docs trước public deployment.
- ResumeProfile, embedding, match và AI-derived output phải hỗ trợ delete/expiry theo cùng owner scope.
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
- CV raw text/embedding không xuất hiện trong log, error, tracing hoặc API response.
- Skill trend thiếu denominator/query evidence: deterministic analytics validation reject.
- Crawl request chứa host ngoài allow-list hoặc vượt policy: deterministic source boundary reject.
