# V3-002 — Provider/privacy/cost và pgvector spike

## Trạng thái

`blocked` cho live provider latency/evaluation; phần official-doc review, cost model và pgvector compatibility đã hoàn tất. Provider generation đã chuyển sang DeepSeek theo [ADR-008](../decisions/0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md), nhưng ADR vẫn `Proposed`.

Environment check chỉ ghi boolean, không đọc/in secret:

```text
DEVRADAR_DEEPSEEK_API_KEY_PRESENT=false
GEMINI_API_KEY_PRESENT=false
GOOGLE_API_KEY_PRESENT=false
OLLAMA_PRESENT=false
NVIDIA_SMI_PRESENT=false
```

Không có credential/runtime hợp lệ để đo model latency hoặc account availability. Key người dùng dán trong chat không được sử dụng, ghi vào workspace hay command; phải revoke/rotate trước khi dùng live. Task không được đánh dấu `Done`; ADR-007 giữ lịch sử và đã `Superseded`, [ADR-008](../decisions/0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md) giữ `Proposed`.

## Provider shortlist

| Candidate | Generation | Embedding | Privacy boundary | Outcome |
|---|---|---|---|---|
| DeepSeek | `deepseek-v4-flash`; JSON Output, non-thinking; USD 0.0028/M cache hit, 0.14/M cache miss, 0.28/M output | Không thấy embedding endpoint trong bộ API docs chính thức được review; không suy luận từ OpenAI-compatible | Privacy policy mô tả thu thập input, dùng để cải thiện/train, retention theo mục đích và xử lý/lưu tại Trung Quốc | Preferred generation candidate, chờ live gate |
| OpenAI | `gpt-5.4-nano-2026-03-17`; Structured Outputs; USD 0.20/M input, 1.25/M output | `text-embedding-3-small`; USD 0.02/M input; explicit 1536 dimensions | Không train API data mặc định; abuse log có thể giữ content tới 30 ngày; `store=false` không tự tạo ZDR | Superseded cho generation; embedding candidate chưa được chọn |
| Gemini | `gemini-2.5-flash-lite`; USD 0.10/M input, 0.40/M output | `gemini-embedding-001`; USD 0.15/M; 128–3072 dimensions | Paid service không dùng data để improve; logging/ZDR/caching có điều kiện | Alternative, chưa thêm second provider |
| Local | Không có Ollama/GPU | Không có local embedding runtime | Data local | Defer do runtime/footprint và chưa có quality evidence |

Official sources: DeepSeek [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing/), [Create Chat Completion](https://api-docs.deepseek.com/api/create-chat-completion/), [JSON Output](https://api-docs.deepseek.com/guides/json_mode/), [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/), [Rate Limit](https://api-docs.deepseek.com/quick_start/rate_limit), [Open Platform Terms](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) và [Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html); OpenAI [GPT-5.4 nano](https://developers.openai.com/api/docs/models/gpt-5.4-nano), [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small), [embedding API](https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create), [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create) và [data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint); Google [pricing](https://ai.google.dev/gemini-api/docs/pricing), [ZDR](https://ai.google.dev/gemini-api/docs/zdr) và [embedding model](https://ai.google.dev/gemini-api/docs/models/gemini-embedding-001).

## Cost model

Workload assumption để so sánh, chưa phải actual usage: 1.500 input + 300 output token/extraction và 500 token/job embedding.

| Workload | DeepSeek generation (cache miss) | OpenAI generation | Gemini generation |
|---|---:|---:|---:|
| Extraction / job | USD 0.000294 | USD 0.000675 | USD 0.000270 |
| 1.000 extraction | USD 0.294 | USD 0.675 | USD 0.270 |
| 1.000 embedding | Chưa có provider | USD 0.010 | USD 0.075 |
| 1.000 extraction + embedding | Chưa tính embedding | USD 0.685 | USD 0.345 |

Giá được đọc ngày 2026-08-21 và có thể thay đổi; actual token usage/cost phải thay bảng assumption trước khi ADR được accept. Retry, cached input, batch discount, tax và currency conversion chưa tính.

## pgvector compatibility

Base Compose `postgres:18.6-alpine3.24` không trả row cho `pg_available_extensions.name='vector'`, nên không thể chỉ chạy `CREATE EXTENSION` trên image hiện tại.

Spike dùng official pinned image:

```text
pgvector/pgvector:0.8.6-pg18-bookworm
digest sha256:2ba9ca5f2e7daa0f0e7723cba1ee9167bab54efd3640516a44ac1a928dd67e7a
PostgreSQL 18.6 (Debian)
pgvector 0.8.6
```

Disposable database đã:

1. `CREATE EXTENSION vector`;
2. insert 1.000 row `vector(1536)`, gồm 800 active row và source bucket;
3. chạy filtered exact cosine top-10 với B-tree filter;
4. tạo HNSW `vector_cosine_ops` và chạy indexed top-10;
5. xác nhận `vector_dims=1536` cho toàn bộ row;
6. stop/remove container sau spike.

Observed local one-shot query evidence:

| Query | Plan | Execution |
|---|---|---:|
| Filter `status=active, source_bucket=1`, exact cosine trên 267 candidate | B-tree filter + top-N sort | 3.749 ms |
| Unfiltered cosine top-10 | HNSW index scan | 0.517 ms |

Đây là compatibility micro-benchmark trên synthetic vectors, cache/hardware local và `enable_seqscan=off` cho HNSW proof; không phải production SLO hoặc quality/recall evidence. Với dataset <=1.000, exact search là default được đề xuất. HNSW chỉ bật sau query-pressure/recall benchmark V3-005. Official pgvector behavior/version/image nằm tại [pgvector repository](https://github.com/pgvector/pgvector).

## Privacy decision boundary

- V3 spike chỉ gửi synthetic job text, không file/raw HTML, header, cookie, secret, source JD hoặc CV.
- Chat Completion request dùng non-thinking, no tools/files/grounding và JSON Output; DeepSeek privacy policy vẫn được coi là external processing/retention boundary.
- Không log prompt/output đầy đủ. Persist hash, model/schema/prompt version, token/latency/cost counters và validated result.
- External provider failure giữ deterministic canonical ingestion hoạt động và trả `needs_review`/pending extraction.
- CV vẫn bị cấm trong provider scope này; V5 phải có privacy decision riêng.

## Điều kiện mở khóa

Operator cung cấp key DeepSeek mới đã rotate qua `DEVRADAR_DEEPSEEK_API_KEY` bằng secret mechanism ngoài Git/log, với spend cap nhỏ (đề xuất USD 1 cho spike). Chạy development split qua module spike đã khóa, tối thiểu 3 repeat/case, ghi actual model ID, system fingerprint, usage, latency p50/p95, cost và schema/error behavior. Không dùng held-out làm prompt tuning; held-out chỉ chạy release evaluation sau khi prompt/schema đã khóa. Embedding provider vẫn là gate riêng trước V3-005.
