# AI, embeddings và agentic workflow

## 1. Nguyên tắc

AI là lớp bổ sung có giới hạn, không phải nguồn sự thật hoặc orchestration mặc định.

1. **Deterministic-first:** structured data, parser và taxonomy rule chạy trước.
2. **Model output is untrusted:** parse, validate, bound và encode trước khi dùng.
3. **Evidence-backed:** field/insight/match explanation phải trỏ tới input hoặc aggregate query.
4. **Version everything:** input hash, schema, extractor, prompt, model, embedding và scoring version.
5. **Provider-agnostic boundary:** OpenAI, Gemini hoặc local model là adapter; không khóa provider trước V3 evaluation.
6. **Bounded agency:** model không tự chọn arbitrary URL, chạy shell/SQL, ghi database hoặc gửi alert.

## 2. Phase boundary

| Capability | Phase | Trạng thái trước phase |
|---|---|---|
| Deterministic extraction | V1 | Required |
| LLM structured extraction fallback | V3 | Proposed |
| Job classification và bounded summary | V3 | Proposed, evidence-validated |
| Skill taxonomy assisted mapping | V3 | Proposed, human/eval governed |
| Embedding và pgvector | V3 | Proposed |
| Planner/validator/analyst graph | V4 | Proposed |
| Resume extraction/matching | V5 | Proposed |
| LLM-written alert/explanation | V5 | Optional; deterministic evidence required |

Không thêm SDK/model dependency trong V1–V2 chỉ để chuẩn bị.

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

Schema thực tế phải giới hạn enum, collection size, string length và numeric range. Evidence span phải tồn tại trong canonical input sau normalization; nếu không tìm thấy, field không được auto-accept.

Job classification dùng taxonomy/version và trả evidence giống extraction field. AI summary phải ngắn, chỉ tổng hợp claim được hỗ trợ bởi canonical JD và bị reject nếu thêm salary, skill, benefit hoặc requirement không có evidence.

## 4. Validation và retry

Validation theo thứ tự:

1. response parse thành đúng structured format;
2. schema/type/range validation;
3. evidence verification với input;
4. domain invariant và taxonomy mapping;
5. confidence/policy gate;
6. accept, reject hoặc `needs_review`.

Retry chỉ dành cho lỗi transient hoặc malformed structured output có khả năng sửa. Không retry vô hạn hoặc retry hallucination bằng cùng input/prompt mà không đổi chiến lược. Default tối đa hai model attempts cho một extraction; vượt mức thì `needs_review`/fallback. V4 graph có recursion/step cap cứng.

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

Baseline held-out `deterministic-keyword-v1`: skill F1 `0.9545`, unsupported skill `0.0455`, deterministic complete `0.6250`. Gate extraction V3 trên cùng dataset là skill F1 `>=0.9700`, unsupported skill/hallucination `0`, accepted schema/evidence `1.0` và complete accepted result `>=0.8750`; deterministic level/salary/location không được regression. Cost/latency target chờ measured provider baseline ở V3-002, còn role/summary target chờ taxonomy contract ở V3-004.

### 5.3. Release gate

- model/prompt/schema mới phải chạy cùng held-out suite;
- regression quan trọng chặn release hoặc cần documented waiver có review date;
- sample output đẹp không thay thế aggregate metric;
- provider fallback không được làm đổi schema/domain semantics;
- eval report ghi dataset version, model identifier, prompt version, parameters, date và environment.

## 6. Caching và reproducibility

Cache key tối thiểu gồm:

```text
input_content_hash
+ task/schema version
+ extractor/prompt version
+ model identifier
+ relevant generation parameters
```

JD không đổi và key không đổi thì reuse result đã validated. Đổi prompt/model/taxonomy không overwrite output cũ; tạo extraction version mới và reprocess có kiểm soát.

## 7. Embeddings và semantic search

- PostgreSQL vẫn là system of record; pgvector chỉ được bật ở V3.
- Embedding lưu model/version, dimension, input hash và created time.
- Không so sánh vector từ model/version không tương thích.
- Job embedding dùng canonical text đã xác định; CV embedding dùng `ResumeProfile` được phép xử lý.
- Xóa/expire ResumeProfile phải xóa hoặc vô hiệu embedding và match liên quan.
- Semantic result luôn giữ link tới canonical Job; vector result không bypass status/source filter.
- Không thêm Pinecone/Qdrant trước khi PostgreSQL/pgvector có bottleneck được đo.

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

Input là aggregate query result có cohort, date range, denominator và provenance. Output là structured insight gồm claim, supporting metrics, caveat và query reference. Không được tự query arbitrary SQL hoặc dùng raw CV.

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

## 11. Privacy và retention

- Chỉ gửi minimum necessary content tới external model.
- Không đưa API key, cookie, auth header, raw log hoặc dữ liệu user khác vào prompt.
- CV file gốc mặc định bị xóa sau parsing; raw text không nằm trong telemetry.
- External provider processing phải có config opt-in cho dữ liệu nhạy cảm và được nêu trong UI/docs trước public deployment.
- ResumeProfile, embedding, match và agent output phải hỗ trợ delete/expiry theo cùng owner scope.
- Dataset evaluation không dùng CV/JD chứa PII chưa được loại bỏ hoặc có quyền sử dụng không rõ.

## 12. Cost và failure handling

Mỗi task AI có budget theo request/run và metric: calls, tokens, latency, accepted/rejected, cache hit và estimated cost. Khi provider unavailable, rate-limited hoặc budget hết:

- ingestion deterministic vẫn tiếp tục;
- field AI-only giữ `null`/partial và queue/review theo phase;
- không làm mất raw snapshot hoặc rollback canonical field đã xác nhận;
- không tự chuyển sang provider khác nếu chưa có adapter/evaluation tương đương;
- UI/API nêu rõ dữ liệu AI đang pending/degraded.

## 13. Acceptance scenarios

- Structured parser đủ schema: không có LLM call.
- Model trả malformed JSON, enum lạ hoặc evidence không tồn tại: reject/retry bounded.
- JD chứa “ignore previous instructions” hoặc URL/tool instruction: nội dung được coi là data, không có tool/action.
- Provider timeout/rate limit: canonical ingestion vẫn thành công và trạng thái extraction rõ ràng.
- Cùng cache key: không gọi model lần hai.
- Đổi model/prompt/taxonomy: không reuse cache sai version.
- CV raw text/embedding không xuất hiện trong log, error hoặc AgentRun response.
- Analyst claim không có denominator/query evidence: validation reject.
- Planner đề xuất host ngoài allow-list hoặc vượt policy: deterministic layer reject.
