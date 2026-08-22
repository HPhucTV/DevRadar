# ADR-009: Chấp nhận local multilingual E5 và pgvector cho V3

## Status

Accepted cho V3 local/private deployment. Public production-like exposure vẫn cần V6 capacity, supply-chain và abuse review.

## Date

2026-08-22

## Context

ADR-008 đã chấp nhận DeepSeek cho synthetic generation spike nhưng yêu cầu quyết định embedding riêng trước V3-005. DeepSeek không có embedding endpoint chính thức đã được xác minh; source approvals hiện tại cũng không cho gửi JD thật ra external LLM/provider. DevRadar cần semantic retrieval cho nội dung Việt/Anh mà vẫn giữ JD local.

Official FastEmbed 0.8.0 dùng ONNX Runtime, hỗ trợ Python 3.13 và custom `intfloat/multilingual-e5-small`; model card công bố 384 dimensions, 512 positions, multilingual support và MIT license. Official pgvector 0.8.6 hỗ trợ PostgreSQL 18, exact cosine search và `vector` tới 2.000 dimensions. Official pgvector-python 0.5.0 cung cấp SQLAlchemy `VECTOR` cùng cosine-distance expression.

Spike local tách khỏi project environment đã đo:

| Candidate | Footprint/cache | Synthetic retrieval | Kết luận |
|---|---:|---:|---|
| FastEmbed `paraphrase-multilingual-MiniLM-L12-v2` | khoảng 241 MiB | top-1 `3/4` | Rejected cho first implementation vì miss query backend cơ bản |
| FastEmbed `intfloat/multilingual-e5-small` | `464.78 MiB` | top-1/MRR `20/20`, `1.0` trên 10 role docs Việt/Anh | Accepted cho local V3 baseline |
| External embedding provider | không có local model | chưa chạy | Deferred: thiếu credential và source permission cho external processing |

E5 spike dùng đúng `query:`/`passage:` prefix theo model retrieval contract. Kết quả này chỉ là development smoke project-authored, chưa phải release-quality semantic evaluation hoặc production SLO.

## Decision

- Pin runtime `fastembed==0.8.0`, model `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, ONNX file `onnx/model.onnx`, mean pooling, normalization và dimension `384`.
- Model chỉ chạy local CPU. Application không tự gửi query/JD ra network. Model download là explicit operator/build step từ fixed repository/revision; inference yêu cầu local model path đã có.
- Canonical job embedding input dùng schema `job-embedding-input-v1`, prefix `passage:` và bounded canonical title/description. Query dùng prefix `query:` và bounded length. Persist input hash/schema/model/revision/dimension; vector khác identity không được so sánh.
- Pin database image `pgvector/pgvector:0.8.6-pg18-bookworm` và client `pgvector==0.5.0`.
- Dùng `vector(384)` và exact cosine ordering trước. Không tạo HNSW ở V3-005 vì dataset target gần 500–1.000 và chưa có query-pressure/recall evidence.
- Semantic result luôn join canonical Job và áp status/source filters trước ordering. Score `1 - cosine_distance` là similarity để xếp hạng, không phải xác suất phù hợp.
- Model artifact không commit vào Git. Container có thể prefetch revision cố định ở build; local operator dùng fixed download command. Missing/corrupt model trả safe unavailable state, không fallback sang external provider.

## Official-source basis

- FastEmbed [PyPI 0.8.0](https://pypi.org/project/fastembed/0.8.0/): Python 3.13 support, ONNX Runtime, `TextEmbedding`, custom multilingual E5 example và local inference.
- FastEmbed [supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/): multilingual model dimensions/license/footprint comparison.
- E5 [model card](https://huggingface.co/intfloat/multilingual-e5-small): 384 dimensions, multilingual retrieval, query/passage prefixes, limitations và MIT license.
- pgvector [official repository](https://github.com/pgvector/pgvector): PostgreSQL 18 image tags, extension setup, exact/cosine search và index limits.
- pgvector-python [official repository](https://github.com/pgvector/pgvector-python#sqlalchemy): SQLAlchemy vector mapping và distance operators.

## Alternatives considered

### OpenAI/Gemini embedding

Deferred. Runtime footprint nhỏ hơn và managed inference dễ vận hành hơn, nhưng cần credential mới, privacy/source permission và external latency/cost evidence. Không được tự chuyển provider khi local model lỗi.

### Smaller multilingual MiniLM FastEmbed model

Rejected cho baseline này. Footprint gần một nửa E5 nhưng miss một trong bốn smoke query cơ bản; release không nên đổi privacy lấy quality regression khi chưa có áp lực storage/image rõ ràng.

### External vector database hoặc HNSW ngay

Rejected. PostgreSQL đã là system of record; exact pgvector search đủ cho target hiện tại. Chỉ thêm HNSW/worker/cache khi V3-006 đo query pressure và recall/latency.

## Consequences

### Positive

- JD/query không rời máy;
- Việt/Anh dùng cùng model space;
- model/vector identity có thể tái lập và re-embed khi đổi version;
- exact search giữ filter/domain join đơn giản.

### Trade-offs

- model cache khoảng 465 MiB và tăng thời gian build/cold start;
- explicit download/cache lifecycle cần runbook;
- CPU inference giới hạn throughput, nên endpoint chỉ local/private trước V6 hardening;
- development smoke nhỏ chưa chứng minh semantic quality trên 500 job thật.

## Acceptance gate

- fixed-revision download và local inference không cần credential;
- dimension/finite-vector/input-bound tests pass;
- PostgreSQL migration, model identity, exact cosine ordering và status/source filters pass trên pgvector 0.8.6;
- API không trả raw vector/model path/JD secret và có bounded query;
- V3-006 mở rộng fixed evaluation, đo p50/p95/cost/footprint và chỉ đóng phase khi scale gate đạt.
