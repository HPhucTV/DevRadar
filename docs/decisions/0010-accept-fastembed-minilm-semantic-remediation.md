# ADR-010: Chấp nhận FastEmbed multilingual MiniLM cho semantic retrieval V3

## Status

Accepted; supersedes ADR-009 cho embedding runtime V3.

## Date

2026-08-22

## Context

V3-006 đã chạy fixed held-out semantic evaluation trên `intfloat/multilingual-e5-small` và phát hiện quality gate chưa đạt: Top-1 `0.7917`, MRR `0.8819`, cross-language Top-1 `0.5000`. Development run cũng cho thấy query tiếng Việt về Python/FastAPI bị xếp sau Java backend, nên vấn đề nằm ở chất lượng cross-language của model/input space chứ không phải exact cosine hoặc pagination.

ADR-009 yêu cầu không tuning trên held-out. Vì vậy một development fixture riêng đã được khóa trước model selection:

- file: `tests/fixtures/ai/semantic_retrieval_dev_v2.json`;
- SHA-256: `9fa2e922c3e4e1d7657d5455fffdbbbd04f6b9173fe7f4d8b48b83cff0c78f29`;
- 12 synthetic documents, 24 queries, 12 cross-language cases;
- provenance: `project-authored-synthetic-no-third-party-content`.

Official FastEmbed supported-model metadata mô tả `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` là multilingual khoảng 50 ngôn ngữ, 384 dimensions, Apache-2.0 và không yêu cầu query/document prefix. FastEmbed 0.8.0 cung cấp model này qua artifact ONNX `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`.

## Decision

- Dùng `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` làm local embedding model V3.
- Pin ONNX artifact source `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q` tại revision `faf4aa4225822f3bc6376869cb1164e8e3feedd0`.
- Giữ `fastembed==0.8.0`, CPU-only inference, normalization và exact pgvector `vector(384)`.
- Đổi input identity thành `job-embedding-input-v2`; canonical title/description vẫn giữ nguyên nhưng query và passage truyền vào model không thêm `query:`/`passage:` prefix vì metadata chính thức ghi prefix không cần thiết.
- Giữ model download explicit tại build/operator step, SHA-256 validate các file cần thiết và inference local-only. Không download hoặc fallback external trong request.
- Backfill toàn bộ current `Job` theo identity mới; embedding cũ của ADR-009 trở thành stale derived data và không được dùng để rank.

Evidence model selection (development trước, held-out một lần sau khi chọn):

| Metric | Development v2 | Frozen held-out v1 | Target |
|---|---:|---:|---:|
| Top-1 | `1.0000` | `0.9583` | `>=0.9000` |
| MRR | `1.0000` | `0.9792` | `>=0.9500` |
| Recall@5 | `1.0000` | `1.0000` | `1.0000` |
| Cross-language Top-1 | `1.0000` (12 cases) | `0.9000` (10 cases) | `>=0.8500` |

Footprint đo local sau download là `240.46 MiB` (FastEmbed metadata khoảng `0.22 GB`), thấp hơn cache E5 hiện tại `464.78 MiB`. Held-out có một miss DevOps ở rank 2; đây là lỗi quality còn lại nhưng không vi phạm release target.

## Alternatives considered

### Giữ `intfloat/multilingual-e5-small`

Rejected cho V3 release vì không đạt ba quality target trên frozen held-out và có lỗi cross-language tái hiện ở development.

### `intfloat/multilingual-e5-large`

Deferred. Đây là candidate multilingual hợp lệ nhưng footprint FastEmbed metadata khoảng `2.24 GB`, lớn hơn nhiều so với nhu cầu portfolio hiện tại. Chưa có bằng chứng development cho thấy chi phí đó cần thiết sau khi MiniLM đã vượt gate.

### `sentence-transformers/paraphrase-multilingual-mpnet-base-v2`

Deferred. Footprint khoảng `1.0 GB`, dimension `768`; chưa cần đổi dimension/migration khi MiniLM 384d đã vượt gate.

### External embedding provider hoặc HNSW/vector database riêng

Rejected ở V3. Chúng làm tăng privacy/cost/ops boundary; PostgreSQL exact search và local model đã đáp ứng gate hiện tại.

## Consequences

### Positive

- Cross-language retrieval trên fixture được cải thiện và vượt release target.
- Model nhẹ hơn, license Apache-2.0, vẫn local/private và giữ dimension 384 nên không cần đổi kiểu pgvector.
- Input contract rõ ràng theo model metadata, không mang prefix E5 sang model không cần prefix.

### Trade-offs

- Đổi model revision và input schema buộc backfill derived embeddings.
- Một số thứ hạng ngoài fixture vẫn có thể cần đánh giá trên inventory thật; V3 không tuyên bố production quality chỉ từ synthetic data.
- `fastembed` cảnh báo model ONNX hiện dùng mean pooling; behavior này được pin cùng artifact và phải giữ trong regression evidence.

## Official-source basis

- FastEmbed supported models: <https://qdrant.github.io/fastembed/examples/Supported_Models/>
- FastEmbed model registry/API: <https://github.com/qdrant/fastembed/blob/main/fastembed/text/text_embedding.py>
- FastEmbed retrieval input guidance: <https://qdrant.github.io/fastembed/Getting%20Started/>
- Model card/license: <https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2>

## Acceptance gate

- Model source/revision, required file hashes và dimension được test.
- Query/passage embedding không thêm prefix và được test bằng exact captured input.
- Backfill mới idempotent; stale ADR-009 embeddings không được chọn.
- Semantic API filters, score semantics, unavailable/corrupt model safety và no-raw-vector contract vẫn pass.
- V3-006 chỉ đóng sau khi approved inventory đạt scale gate và analytics coverage có bằng chứng.
