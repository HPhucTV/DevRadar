# ADR-007: Đề xuất OpenAI-first cho V3 và pgvector 0.8.6

## Status

Superseded by [ADR-008](0008-proposed-deepseek-v4-flash-generation-and-embedding-boundary.md). Giữ nguyên lịch sử đề xuất OpenAI; không dùng làm provider generation hiện hành.

## Date

2026-08-21

## Context

V3 cần một provider structured extraction, một embedding model và PostgreSQL vector capability. V3-001 đã khóa held-out dataset/target; provider chỉ được `Accepted` khi có measured latency/cost, privacy boundary và regression trên dataset đó. Repository hiện không có OpenAI/Gemini credential, Ollama hoặc GPU runtime, nên không có bằng chứng live inference hợp lệ.

Spike local đã xác minh PostgreSQL `18.6` + pgvector `0.8.6`, `vector(1536)`, cosine search, filter và HNSW index. Base image `postgres:18.6-alpine3.24` hiện không cung cấp extension `vector`, nên V3-005 sẽ phải đổi image/migration có kiểm soát nếu ADR này được accept.

## Proposed decision

Khi live gate đạt, dùng:

- OpenAI Responses API với snapshot `gpt-5.4-nano-2026-03-17` cho extraction fallback đầu tiên;
- Structured Outputs JSON Schema, không tool, foreground, `store=false`, bounded input/output;
- `text-embedding-3-small` với explicit `dimensions=1536` cho job text;
- pgvector `0.8.6` trên PostgreSQL `18`, exact cosine search trước; chỉ bật HNSW khi benchmark dataset/query pressure chứng minh cần;
- lưu provider/model/dimension/input hash/prompt-schema version; embedding khác model/version/dimension không được so sánh;
- chỉ gửi public JD field tối thiểu trong V3. CV/ResumeProfile không được gửi bằng policy này.

`gpt-5.4-nano` được ưu tiên hơn alias mới không có dated snapshot vì official model card ghi rõ use case extraction, Structured Outputs và snapshot dated. `text-embedding-3-small` rẻ hơn candidate Gemini embedding hiện tại và 1536 nằm dưới pgvector `vector` HNSW limit 2.000 dimensions.

## Official-source basis

- OpenAI [GPT-5.4 nano model card](https://developers.openai.com/api/docs/models/gpt-5.4-nano): extraction use case, Structured Outputs, giá và snapshot `2026-03-17`.
- OpenAI [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create): typed text/JSON output, bounded output và request options.
- OpenAI [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) và [embedding API](https://developers.openai.com/api/reference/ruby/resources/embeddings/methods/create): giá, token limits, usage response và configurable dimensions.
- OpenAI [data controls](https://developers.openai.com/api/docs/guides/your-data#default-usage-policies-by-endpoint): API data không dùng để train mặc định; abuse monitoring có thể giữ customer content tới 30 ngày; Responses/embeddings có ZDR eligibility với điều kiện nêu trong docs.
- Google [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing), [ZDR](https://ai.google.dev/gemini-api/docs/zdr) và [embedding docs](https://ai.google.dev/gemini-api/docs/embeddings): cơ sở so sánh paid-data policy, cost, dimensions và model-space migration.
- pgvector [official repository](https://github.com/pgvector/pgvector): PostgreSQL 18 image tags, extension setup, exact/HNSW behavior, cosine operator và dimension limits.

## Alternatives considered

### GPT-5.6 Luna alias

Không chọn làm default đầu tiên dù giá gần tương đương và Structured Outputs được support. Official model page hiện không công bố dated snapshot riêng; reproducibility của extraction evaluation quan trọng hơn dùng alias mới nhất.

### Gemini 2.5 Flash-Lite + Gemini Embedding

Candidate hợp lệ và listed generation cost thấp hơn. Paid service không dùng prompt/response để improve product; ZDR vẫn có điều kiện và logging/caching boundary. Chưa chọn vì không có credential/latency/evaluation evidence, embedding paid cost cao hơn và thêm provider surface thứ hai không tạo giá trị cho first implementation.

### Local model/Ollama

Defer. Máy hiện không có Ollama/GPU runtime; tải model/runtime lớn chỉ để tránh một API key không phù hợp lean portfolio scope và chưa có quality/latency evidence cho Việt/Anh extraction.

### External vector database

Rejected trong V3. PostgreSQL vẫn là system of record; pgvector compatibility/latency đủ cho dataset hiện tại và không có measured bottleneck cần Pinecone/Qdrant.

## Consequences nếu Accepted

### Positive

- one-provider implementation nhỏ, dated generation snapshot và strict schema;
- embedding dimension tương thích trực tiếp với pgvector HNSW;
- estimated list cost cho 1.000 extraction + embedding dưới USD 1 theo workload assumption của spike;
- PostgreSQL giữ canonical filter/status/source cùng vector query.

### Trade-offs

- external API content có abuse-monitoring retention mặc định; `store=false` không đồng nghĩa Zero Data Retention;
- embedding model không có dated snapshot công khai, nên response model ID/dimension phải được persist và model drift buộc re-evaluation/re-embed;
- provider outage phải degrade về deterministic/needs-review, không chặn ingestion;
- Compose database image và migration sẽ đổi ở V3-005, không trong spike này.

## Acceptance gate

Chỉ đổi ADR sang `Accepted` sau khi project-scoped credential, spend cap và development-split smoke chứng minh:

- model/account availability đúng ID;
- tối thiểu 3 run/case để ghi latency p50/p95 và usage tokens;
- estimated cost từ actual usage, không chỉ workload assumption;
- `store=false`, no-tools và schema request/response được negative-test;
- held-out evaluation đạt target V3-001 trước canonical persistence;
- credential không xuất hiện trong Git/log/error.

Chi tiết spike và blocker nằm tại [V3-002 evidence](../evidence/V3-002-provider-privacy-cost-pgvector-spike.md).
