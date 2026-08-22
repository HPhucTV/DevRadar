# V3-005 Embeddings, semantic search và skill trends — Design Spec

**Ngày:** 2026-08-22
**Trạng thái:** Đã được user ủy quyền triển khai tự động; ADR-009 Accepted
**Phase:** V3 — AI extraction, taxonomy và semantic search

## Mục tiêu

- persist version-safe local job embeddings trong PostgreSQL/pgvector;
- mở additive keyword/semantic query trên `GET /api/v1/jobs` với status/source filters;
- mở `GET /api/v1/skills` và `GET /api/v1/skill-trends` có cohort, denominator và extraction coverage;
- có bounded local model download/backfill path, không external provider hoặc raw vector response.

## Kiến trúc

`intelligence.embeddings` sở hữu canonical input, fixed-revision local E5 adapter, persistence/backfill và exact cosine query expression. `JobEmbedding` là derived data; PostgreSQL Job vẫn canonical source. Khi Job hash đổi, embedding cũ giữ audit nhưng không được query như current.

Trend/frequency đọc latest accepted `ExtractionResult` cùng current `Job.job_content_hash`; aggregate trong application cho dataset V3 <=1.000 thay vì thêm `Skill`/`JobSkill` materialization chưa cần. Denominator là toàn cohort Job; `analyzedJobs`/coverage công bố phần có accepted extraction.

## Database contract

`job_embeddings`:

- UUID `id`, `job_id`, `input_hash`, `input_schema_version`;
- `provider=local_fastembed`, model ID/revision, dimension 384;
- `embedding vector(384)`, latency và `created_at`;
- unique logical key theo job/hash/schema/provider/model/revision;
- check hash/revision/dimension/latency; FK Job;
- không HNSW trong V3-005.

Migration tạo extension `vector` trước table và drop table trước extension ở downgrade. Compose đổi sang pgvector 0.8.6 PostgreSQL 18 image.

## API contract

### `GET /api/v1/jobs`

Thêm optional `query`, `searchMode=keyword|semantic`, `skill` và response `relevanceScore` nullable. Keyword dùng literal case-insensitive match. Semantic yêu cầu local model, chỉ join current compatible embedding, áp filter trước exact cosine order; pagination stable bằng distance rồi Job ID. `relevanceScore` không phải probability.

### `GET /api/v1/skills`

Paginated skill frequency với `status`, `sourceId`, optional date range. Response có `cohortSize`, `analyzedJobs`, `coverage`, taxonomy/extraction version, count/share per skill. Skill ordering count desc rồi name asc.

### `GET /api/v1/skill-trends`

Bounded window tối đa 366 ngày; `cohort=firstSeenAt|postedAt`, `granularity=day|week|month`, filters status/source và `topSkills<=20`. Mỗi bucket trả period start, denominator, analyzed jobs, coverage và skill count/share. Empty bucket không được bịa data.

## Failure/privacy

- missing/corrupt local model => safe 503; không download trong request và không fallback external;
- query tối đa 300 chars, không log raw query/vector;
- vector length/non-finite output reject trước persistence/query;
- model path/vector/raw extraction/JD không xuất hiện trong API;
- accepted extraction missing làm coverage giảm, không đổi denominator;
- status/source filter luôn áp trước semantic rank/trend aggregate.

## Non-goals

HNSW, Redis, distributed embedding worker, external embedding API, public rate-limit/auth, cross-source dedup, ResumeProfile/CV embedding và V3 closeout.
