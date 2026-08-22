# V4-001 Deterministic baseline và agent tool policy — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Đã được user xác nhận  
**Phase:** V4 — Agentic decision layer

## Mục tiêu

V4-001 khóa baseline, typed decision contract và default-deny tool policy cho ba responsibility `planner`, `validator` và `analyst` trước khi đánh giá LangGraph. Agent chỉ được đề xuất quyết định từ input read-only đã giới hạn; deterministic application layer tiếp tục sở hữu policy check, retry cap, transaction và persistence.

Task này chỉ tạo design/baseline contract. Không thêm LangGraph, provider SDK, dependency V4, migration, endpoint hoặc runtime agent.

## Các hướng đã cân nhắc

### 1. Thêm LangGraph và thiết kế policy trong lúc implement

Rejected. Cách này trộn framework spike với security/measurement contract, khiến không thể biết graph tạo giá trị hay chỉ thay đổi implementation.

### 2. Cho agent gọi workflow hiện hữu qua mutation tools

Rejected. Planner/validator/analyst chưa có evaluation chứng minh quyền mutation là cần thiết; trao quyền sớm làm tăng blast radius và cho model chen vào policy/transaction boundary.

### 3. Khóa baseline, typed decision và read-only tool policy trước

Accepted. Đây là slice nhỏ nhất cho phép V4-002 so sánh LangGraph với deterministic workflow bằng cùng input/output và giữ canonical state an toàn khi model/graph lỗi.

## Baseline hiện hữu

V4 không thay các workflow dưới đây. Chúng là control group cho mọi spike/implementation agent về sau.

| Responsibility | Deterministic baseline | Evidence hiện có |
|---|---|---|
| `planner` | Schedule slot, transient-only retry tối đa ba attempt, bounded backoff, source health/anomaly và quarantine/recovery | [V2 direct orchestration](../../evidence/V2-002-direct-orchestration.md), [V2 source health](../../evidence/V2-004-source-health-and-quarantine.md), [V2 closeout](../../evidence/V2-006-v2-closeout.md) |
| `validator` | Schema/evidence validation, deterministic extraction, versioned cache và `accepted`/`rejected`/`needs_review` outcomes | [V3 evaluation baseline](../../evidence/V3-001-evaluation-dataset-and-baseline.md), [V3 extraction result](../../evidence/V3-003-extraction-result-cache.md), [V3 closeout](../../evidence/V3-006-v3-closeout.md) |
| `analyst` | Predefined `/skills` và `/skill-trends` aggregates với fixed cohort, denominator, analyzed coverage và stable ordering | [V3 analytics evidence](../../evidence/V3-005-embeddings-search-trends.md), [V3 closeout](../../evidence/V3-006-v3-closeout.md) |

Baseline comparison suite của V4 dùng project-authored synthetic/fixture input và frozen expected outcomes; không gọi live source hoặc dùng raw CV/JD thật. Dataset/version/hash phải được khóa trước lần agent evaluation đầu và không được sửa nhãn theo output model.

### Metric được đặt trước

| Responsibility | Metric bắt buộc | Baseline/gate |
|---|---|---|
| Tất cả | Decision schema validity | `100%` |
| Tất cả | Policy/tool violation rate sau application validation | `0` |
| `planner` | Exact policy outcome trên schedule/retry/quarantine scenarios | `100%` cho deterministic baseline; agent không được regression safety case |
| `validator` | Unsupported-evidence acceptance rate | `0` |
| `validator` | Skill precision/recall reference | `0.9545/0.9545` trên V3 deterministic evaluation; V4 comparison phải báo cùng dataset/version |
| `analyst` | Claim có valid query reference, cohort và denominator | `100%` |
| `analyst` | Unsupported aggregate claim rate | `0` |

Latency, token và cost được ghi lại nhưng chưa đặt SLO khi chưa có V4 runtime measurement. V4-006 chỉ giữ một responsibility agent nếu nó cải thiện metric usefulness/accuracy đã chọn mà không làm giảm safety gate; nếu không, deterministic baseline được giữ và phần agent tương ứng bị loại.

## Typed decision contract

Ba responsibility dùng internal decision envelope chung. Đây không phải public API và không tạo persistence schema trong V4-001.

```text
DecisionEnvelope
  schema_version: literal `agent-decision-v1`
  responsibility: planner | validator | analyst
  decision: responsibility-specific enum
  input_refs: non-empty bounded list of `DecisionRef`
  evidence_refs: bounded list of `DecisionRef` present in supplied input
  reason_code: safe responsibility-specific enum
  confidence: finite number in [0, 1] | null
  decision_data: responsibility-specific typed payload
```

`DecisionRef` chỉ có `kind`, opaque `id`, input `content_hash`/`version` khi resource cung cấp và không có URL tùy ý hoặc raw content. `evidence_refs` phải là subset của `input_refs`; `decision_data` phải khớp `responsibility + decision` theo discriminated schema. Unknown/missing/extra field, enum lạ, reference ngoài input, non-finite confidence hoặc payload vượt limit đều bị reject trước application. `reason_code` dùng safe enum; raw chain-of-thought, prompt, raw JD/CV và free-form explanation không thuộc contract.

Các responsibility dùng cùng version nhưng reason/decision data enum riêng:

- `planner.reason_code`: `healthy_due`, `transient_failure`, `degraded_source`, `quarantined_source`, `retry_cap_reached`, `budget_exhausted`, `insufficient_evidence`;
- `validator.reason_code`: `schema_valid`, `schema_invalid`, `evidence_missing`, `evidence_unsupported`, `transient_failure`, `retry_cap_reached`, `ambiguous_input`;
- `analyst.reason_code`: `evidence_supported`, `missing_denominator`, `missing_query_reference`, `unsupported_metric`, `insufficient_coverage`, `ambiguous_claim`.

`decision_data` chỉ chứa field cần cho decision: planner dùng `priority` (`low|normal|high`) và bounded `suggested_delay_seconds` khi `defer`; validator dùng optional `retry_strategy` từ allow-list input khi `retry_with_strategy`; analyst dùng `claim_code`, supporting metric refs và caveat codes khi `publish_insight`. Không responsibility nào được gửi arbitrary string để application diễn giải thành policy/action. `confidence` chỉ là metadata để evaluation; application không dùng nó để bypass safety gate.

### Planner decision

Input chỉ gồm source identity cùng aggregate health/run fields đã cấp: health status/reason, last complete success, failure/change/new-job rate, schedule policy, retry state và budget/cap hiện hành.

Decision enum:

- `keep_schedule`;
- `defer`;
- `recommend_retry`;
- `request_quarantine_review`;
- `needs_review`.

Planner có thể đề xuất priority/delay/retry strategy trong bounded enum/range đi kèm decision, nhưng deterministic layer tính lại eligibility, rate limit, attempt cap và earliest allowed time. Planner không được thêm source/URL, unquarantine source, sửa schedule policy hoặc khởi chạy crawl.

### Validator decision

Input chỉ gồm opaque raw/input reference, typed extraction result, safe validation error codes, evidence references, extractor/model version và retry count/cap.

Decision enum được giữ theo `docs/AI.md`:

- `accept`;
- `reject`;
- `retry_with_strategy`;
- `needs_review`.

`retry_with_strategy` chỉ chọn strategy enum đã allow-list; deterministic layer kiểm tra error class, budget và retry cap. `accept` bị reject nếu evidence reference không tồn tại hoặc deterministic schema/evidence gate không đạt. Validator không sửa extraction payload hoặc tự persist kết quả.

### Analyst decision

Input chỉ gồm predefined aggregate result có query reference, cohort, date range, denominator, analyzed count/coverage, metrics và provenance.

Decision enum:

- `publish_insight`;
- `reject_claim`;
- `needs_review`.

`publish_insight` chứa structured claim code/template, supporting metric references và caveat codes; không chứa arbitrary HTML/SQL. Mọi số liệu phải resolve đúng aggregate input. Thiếu denominator, cohort, query reference hoặc metric support luôn bị reject.

## Default-deny tool policy

V4-001 không cấp mutation tool. Tool registry của từng responsibility là allow-list độc lập; tool/argument không khớp exact schema bị từ chối trong code.

| Responsibility | Read-only capability được phép | Bị cấm |
|---|---|---|
| `planner` | Đọc source/run health aggregates theo opaque ID đã cấp | Source config/allow-list mutation, enqueue/crawl, arbitrary URL/HTTP/SQL, unquarantine |
| `validator` | Đọc extraction/result/evidence references theo opaque ID đã cấp | Canonical Job/raw snapshot mutation, retry execution, arbitrary record lookup, external fetch |
| `analyst` | Đọc predefined aggregate resource theo query reference đã cấp | Arbitrary SQL, raw Job/CV access, query shape tự tạo, write/export action |
| Tất cả | Không có capability ngoài allow-list riêng | Shell, filesystem path, secret/config access, arbitrary HTTP, destructive database operation, cross-responsibility tool |

Content từ source/JD/CV và aggregate label luôn ở data channel, không thể thay instruction, policy hoặc tool registry. Không render model output thành raw HTML, filename/path, SQL hay command.

## Deterministic application boundary

Luồng xử lý bắt buộc:

1. Application tạo bounded read-only input từ canonical references và policy hiện hành.
2. Responsibility trả đúng một typed decision envelope trong hard limits.
3. Validator deterministic kiểm schema, reference closure, tool audit, policy, budget và responsibility-specific invariant.
4. Chỉ application use case hiện hữu mới quyết định áp dụng action trong transaction; agent không có database session hoặc mutation handle.
5. Invalid/timeout/provider unavailable/budget exhausted chuyển sang deterministic fallback hoặc `needs_review`; không retry vô hạn và không đổi canonical state chỉ vì graph fail.

Các cap bắt buộc phải có trước runtime agent: step, tool call, model attempt, timeout, concurrency, token và estimated cost. Giá trị cụ thể được đo/chốt trong V4-002/V4-003; trước đó không có runtime agent để dùng default giả.

## Audit và dữ liệu nhạy cảm

V4-001 chưa thêm `AgentRun`. Contract audit cho V4-003 chỉ được phép giữ responsibility/version, input reference/hash, validated decision, safe reason/evidence reference, status, retry relation, latency, usage/cost và correlation ID.

Audit/log không giữ raw JD/CV, prompt đầy đủ, chain-of-thought, secret, embedding hoặc model free-form output. Input/output vượt schema bị ghi bằng safe error code và bounded metadata, không echo payload.

## Failure scenarios bắt buộc

- Model/graph timeout, unavailable hoặc trả malformed payload: dùng deterministic baseline hoặc `needs_review`; canonical state không đổi.
- Planner đề xuất host/source ngoài allow-list, vượt rate limit/retry cap hoặc override quarantine: application reject.
- Validator `accept` evidence không tồn tại, output có field hallucinated hoặc yêu cầu retry quá cap: application reject hoặc `needs_review`.
- Analyst thiếu denominator/query reference, claim số liệu không có trong aggregate hoặc yêu cầu arbitrary SQL: reject.
- JD/CV chứa prompt injection, URL/tool/shell instruction: coi là data; không tool/action phát sinh.
- Tool name/argument/cross-responsibility call ngoài exact allow-list: default deny và ghi safe policy violation.
- Audit/log scan: không có raw JD/CV, prompt, secret, vector hoặc chain-of-thought.

## Non-goals

- LangGraph spike hoặc quyết định chọn graph/direct workflow;
- runtime planner/validator/analyst implementation;
- `AgentRun` migration hoặc persistence;
- external provider adapter/model production call;
- public API/OpenAPI change;
- mutation tool, autonomous source onboarding hoặc unbounded reflection/retry;
- V5 matching/dashboard/alert capability.

## Definition of Done

- ba deterministic baseline và evidence source được map rõ;
- typed decision envelope, responsibility enum và validation ownership không mâu thuẫn `docs/AI.md`/architecture;
- default-deny read-only tool matrix và forbidden capability được khóa;
- comparison metric, safety gate, fallback và failure scenarios được đặt trước V4-002;
- spec self-review không còn placeholder/ambiguity ảnh hưởng implementation;
- `TASK_BOARD.md` cục bộ ghi V4-001 `In Progress`; README/roadmap phản ánh V4 đã bắt đầu;
- chưa thêm code, dependency, migration, endpoint hoặc ADR công nghệ.

## Tự kiểm tra spec

Spec không cấp quyền mutation cho model, không biến conceptual contract thành public API, không giả định LangGraph được chấp nhận và không đặt cap/latency SLO thiếu measurement. `planner`, `validator`, `analyst` dùng đúng domain term hiện hành; mọi action/failure đều quay về deterministic application boundary và không thể làm hỏng canonical state.
