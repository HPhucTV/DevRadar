# ADR-008: Đề xuất DeepSeek V4 Pro cho generation spike và tách quyết định embedding

## Status

Accepted cho synthetic generation spike — thay thế lựa chọn provider generation trong ADR-007. DeepSeek Pro đã đạt development/held-out quality gate sau khi thêm deterministic canonicalization boundary. Embedding provider và pgvector vẫn là candidate riêng, chưa được `Accepted`.

## Date

2026-08-21

## Context

Operator chọn tiếp tục V3 bằng DeepSeek. Tài liệu DeepSeek hiện hành đã chuyển API chính sang `deepseek-v4-flash` và `deepseek-v4-pro`; hai alias `deepseek-chat` và `deepseek-reasoner` đã hết thời hạn tương thích từ 2026-07-24. DeepSeek công bố Chat Completions, JSON Output và toggle thinking/non-thinking, nhưng bộ API docs được review không có embedding endpoint chính thức. Vì vậy không được suy luận rằng OpenAI-compatible đồng nghĩa có embedding API.

Repository đã có dataset synthetic `job-extraction-eval-v1` với development/held-out split. Ba nguồn job được duyệt chỉ cho bounded local non-commercial ingestion; approval hiện tại không cho gửi JD nguồn thật hoặc CV tới external LLM. DeepSeek privacy policy mô tả việc thu thập input, dùng input để cải thiện/train công nghệ, retention theo mục đích và xử lý/lưu dữ liệu tại Trung Quốc. Đây là boundary không phù hợp cho dữ liệu nhạy cảm hoặc source content chưa có privacy approval.

## Proposed decision

- Dùng `deepseek-v4-pro` qua `POST https://api.deepseek.com/chat/completions` cho live provider spike trên development split synthetic mà thôi. Pro được chọn từ development comparison với Flash; đây chưa phải kết luận release vì cả hai chưa đạt held-out gate.
- Chọn non-thinking bằng `thinking: {"type": "disabled"}`; không gửi `tools`, `tool_choice`, file, CV, raw HTML hoặc source credential.
- Bật JSON Output bằng `response_format: {"type": "json_object"}`; prompt phải chứa từ `json` và ví dụ schema. Response vẫn là untrusted input: parse bằng schema strict, kiểm tra evidence là substring của input, reject duplicate/unsupported field và không persist raw output.
- Trước strict validation, deterministic canonicalizer áp dụng alias taxonomy cho skill và lấy `levels`, `experience`, `salary`, `location` từ parser trên canonical input. Model không override field đã có parser; ambiguous field giữ `null`. Canonicalization rule được version cùng extraction contract.
- API key đọc từ process `DEVRADAR_DEEPSEEK_API_KEY` hoặc fallback `.env.local` đã bị Git/Docker ignore; environment được ưu tiên. Không ghi key vào tracked file, log, report, command hoặc exception. Base URL/model là constant của spike, không nhận URL tùy ý.
- Ghi lại trong report chỉ model ID trả về, system fingerprint, usage token, latency, cost estimate, schema/error code và match count. Không ghi prompt, output, job text hoặc secret.
- Chạy tối đa 3 repeat/case trên development split để lấy p50/p95 và usage. Không dùng held-out để tuning; chỉ chạy held-out sau khi prompt/schema khóa cho release evaluation.
- Giữ pgvector/PostgreSQL làm candidate system-of-record/vector capability. Embedding provider và model là quyết định riêng, defer tới khi có official API/terms, dimension, cost, latency và evaluation evidence.

## Official-source basis

- DeepSeek [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/): V4 Flash/Pro, model IDs, context/output limits và giá cache hit/miss/output.
- DeepSeek [Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/): OpenAI-format endpoint, JSON response, usage fields và model IDs.
- DeepSeek [JSON Output](https://api-docs.deepseek.com/guides/json_mode/): `response_format=json_object`, prompt phải nói `json`, ví dụ schema và cảnh báo empty/truncated output.
- DeepSeek [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/): `thinking.type=disabled` cho non-thinking và giới hạn parameter theo mode.
- DeepSeek [Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit): concurrency theo account/model và `user_id` isolation.
- DeepSeek [Open Platform Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html): trách nhiệm với input, permission/legal basis và yêu cầu bảo vệ API key.
- DeepSeek [Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html): input collection, training/improvement, retention và nơi lưu trữ/xử lý tại Trung Quốc.

## Alternatives considered

### Tiếp tục OpenAI-first theo ADR-007

Không chọn cho provider generation của spike này theo yêu cầu operator. ADR-007 giữ nguyên lịch sử và được đánh dấu `Superseded`; không sửa nội dung cũ để biến OpenAI thành lựa chọn đã chạy.

### Suy luận DeepSeek có embedding vì tương thích OpenAI

Rejected. Tương thích wire format của Chat Completions không chứng minh tồn tại hoặc tương thích của embeddings. V3-005 cần provider/endpoint riêng hoặc defer.

### Gửi JD thật/CV vào DeepSeek để tăng realism

Rejected. Source approvals chưa bao gồm external LLM; privacy policy nêu input có thể được thu thập, dùng để cải thiện/train và lưu tại Trung Quốc. Spike dùng synthetic content không có URL, email hay third-party JD.

### Thêm SDK DeepSeek/OpenAI

Deferred. HTTP request bằng standard library đủ cho một spike có một endpoint; chỉ thêm SDK nếu có nhiều consumer thật hoặc capability được kiểm chứng yêu cầu.

## Consequences nếu Accepted

### Positive

- model ID hiện hành, non-thinking path nhỏ và chi phí generation thấp;
- JSON mode, usage và fingerprint có thể đo trực tiếp;
- không khóa sai embedding architecture chỉ vì provider compatibility;
- provider outage chỉ ảnh hưởng spike/extraction pending, không làm hỏng deterministic ingestion.

### Trade-offs

- model family không có dated snapshot công khai trong docs được review; phải persist response model/fingerprint và re-evaluate khi thay đổi;
- JSON Output không phải schema enforcement đầy đủ; validation/evidence gate vẫn bắt buộc;
- external processing/retention và cross-border storage làm DeepSeek không phù hợp cho CV hoặc source content chưa được duyệt;
- pgvector migration/embedding chưa thể triển khai chỉ từ spike generation.

## Acceptance gate

Acceptance evidence cho synthetic generation spike:

- key mới đã được rotate sau lần lộ trong chat, nạp ngoài Git/log và chạy được với model ID hiện hành;
- tối thiểu 3 repeat/case trên toàn development split, có actual p50/p95, usage, cost và error behavior — đã đạt;
- schema/evidence validation và no-tools/non-thinking request được negative-test;
- held-out v6 chạy sau khi prompt/schema/canonicalization khóa và đạt target V3-001: schema/evidence `1.0`, skill F1 `1.0`, unsupported skill `0`, level `1.0`, experience `0.875`, salary `1.0`, location `1.0`, complete accepted `0.875`. Các scalar field là contract sau deterministic canonicalization, không phải raw model-only accuracy;
- report không chứa credential, prompt, output, raw JD/CV hay PII.

Không coi acceptance generation là acceptance embedding. ADR riêng hoặc amendment tiếp theo phải chốt embedding trước V3-005.
