# V3-006 — Evaluation, scale và V3 closeout

## 1. Kết luận

**Status:** `complete` ngày 2026-08-22. V3 chuyển `complete`; V4-001 đủ điều kiện `Ready` nhưng chưa triển khai.

Các release gate đều đạt trên dữ liệu và run có thể truy xuất:

- inventory canonical: `3339/500`, toàn bộ từ approved source và run `succeeded + complete`;
- semantic held-out: Top-1 `0.9583`, MRR `0.9792`, Recall@5 `1.0000`, cross-language Top-1 `0.9000`;
- extraction analytics: `1003/3339` accepted current results, coverage `0.3004`, có meaningful cohort và denominator rõ;
- embedding compatibility: `3339/3339` current MiniLM vectors, dimension `384`;
- full PostgreSQL/static/Compose/API gates pass; không có false removal hoặc provider call trên JD thật.

GeoComply/Lever vẫn giữ `permission_required` và không được dùng để lấp inventory. RemoteJobs.org chỉ thuộc cohort `global_remote_it_secondary`; không dùng inventory này để claim thị trường Việt Nam.

## 2. Fixed semantic evaluation

Dataset held-out được khóa trước live evaluation:

```text
dataset       semantic-retrieval-eval-v1
schema        semantic-retrieval-eval-schema-v1
SHA-256       60b9b017c7c2fed1d8d15956ad46c3c7f6206229190734d58a5e03c7b62349ef
provenance    project-authored-synthetic-no-third-party-content
documents     12
held-out      24 queries: vi=12, en=11, mixed=1
cross-lang    10
```

Development-only model selection fixture `tests/fixtures/ai/semantic_retrieval_dev_v2.json` giữ nguyên SHA-256 `9fa2e922c3e4e1d7657d5455fffdbbbd04f6b9173fe7f4d8b48b83cff0c78f29`. Frozen held-out chạy đúng một lần với model hiện hành:

| Metric | Development v2 | Frozen held-out v1 | Target | Gate |
|---|---:|---:|---:|---|
| Top-1 accuracy | `1.0000` | `0.9583` | `>=0.9000` | Pass |
| MRR | `1.0000` | `0.9792` | `>=0.9500` | Pass |
| Recall@5 | `1.0000` | `1.0000` | `1.0000` | Pass |
| Cross-language Top-1 | `1.0000` (12) | `0.9000` (10) | `>=0.8500` | Pass |
| Dimension/finite | `384/true` | `384/true` | `384/all finite` | Pass |
| Monetary cost | local | `USD 0` | report actual | Pass |

Current identity: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, ONNX source `qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q`, revision `faf4aa4225822f3bc6376869cb1164e8e3feedd0`, input schema `job-embedding-input-v2`, dimension `384`. Local model footprint là `252,141,068` bytes (`240.46 MiB`). Không thêm prefix, HNSW hoặc external embedding provider.

Measured held-out latency trên local model: passage p50/p95 `173.833/194.767 ms`, query p50/p95 `110.989/134.160 ms`.

## 3. Approved-source complete run

RemoteJobs.org được duyệt theo [ADR-011](../decisions/0011-accept-secondary-remote-api-cohort.md) và [approval record](../sources/remotejobs-org.md). Run đầy đủ dùng exact registry key, không `--max-items`, crawler sandbox và policy `2 requests/minute`:

| Source/run | Status/coverage | Found | Failed/new/updated/missing/removed | Duration |
|---|---|---:|---|---:|
| `remotejobs-org` / `207c3011-9202-45e3-902c-dd20c4c4cafd` | `succeeded/complete` | `3261` | `0/3261/0/0/0` | `36.85 min` |

Remote snapshot provenance kiểm chứng `3261/3261` URL canonical dạng `https://remotejobs.org/remote-jobs/...`; URL feed `/api/v1/jobs?...` chỉ là transport URL. Run không mở HTML, company URL hoặc `apply_url`. Source health sau run là `healthy`/`source_recovered`.

Inventory hiện tại:

```text
MoMo Careers                          37
NAVER Vietnam Careers via Greenhouse 14
VNG Careers                           27
RemoteJobs.org API                    3261
Total                                 3339
Distinct (source, external_id)        3339
Distinct (source, canonical_url)      3339
```

Không source nào có `items_missing` hoặc `items_removed` trong run mới; failed/partial history trước đó không làm thay đổi lifecycle.

## 4. Extraction, embeddings, search và analytics

Deterministic extractor được nâng thành `deterministic-job-v2`: khi `Job.levels` rỗng, chỉ dùng marker level rõ ràng trong title qua `normalize_levels`; không suy từ số năm kinh nghiệm. Regression test xác nhận fallback này và transaction test xác nhận incomplete result không provider được lưu an toàn.

Backfill hiện tại:

| Derived data | Result |
|---|---:|
| `ExtractionResult` rows | `3339` jobs |
| `accepted` deterministic rule | `1003` |
| `needs_review` (provider chưa được phép cho JD thật hoặc thiếu evidence) | `2336` |
| accepted analytics coverage | `1003/3339 = 0.3004` |
| current compatible MiniLM embeddings | `3339/3339` |
| embedding rerun | `selected=0, created=0, stale_skipped=0` |

Không đọc hoặc gửi `DEVRADAR_DEEPSEEK_API_KEY` trong real-JD backfill; DeepSeek vẫn chỉ là synthetic generation spike theo ADR-008/AI boundary. `needs_review` giữ deterministic payload và không làm mất canonical Job.

API smoke sau khi restart image:

```text
GET /api/v1/health                 -> data.status=ok
GET /api/v1/jobs?searchMode=semantic&query=backend&pageSize=10
  -> HTTP 200, totalItems=3339, 10 rows
GET /api/v1/skills?pageSize=5
  -> cohortSize=3339, analyzedJobs=1003, coverage=0.3004
GET /api/v1/skill-trends?from=2026-01-01&to=2026-12-31&topSkills=5
  -> cohortSize=3339, analyzedJobs=1003, one bounded bucket
```

Semantic API warm baseline: 10 calls, HTTP 200; p50 `124.43 ms`, p95 `301.72 ms`, 10 rows/request. PostgreSQL exact compatible-vector top-10 query `EXPLAIN (ANALYZE, BUFFERS)` có planning `3.854 ms`, execution `14.231 ms`. Đây là local portfolio baseline, chưa phải public-concurrency SLO.

## 5. V3 exit-criteria audit

| Roadmap criterion | Evidence | Status |
|---|---|---|
| `>=500` canonical Job từ approved/reproducible runs | `3339` canonical Job; source/external ID và URL đều distinct | Pass |
| Accuracy/hallucination/review/cost đạt held-out target | V3-002 extraction baseline và frozen semantic suite đạt target; local semantic cost `USD 0` | Pass |
| Structured parser đủ dữ liệu không gọi LLM | `1003` deterministic accepted; provider không tham gia ingestion/backfill | Pass |
| Malformed/injected output bị chặn | V3-001/V3-003/V3-004 regression suite + full PostgreSQL suite | Pass |
| Model/prompt/schema/cache versioning | extractor v2, embedding revision/schema, semantic fixture hash và tests | Pass |
| Provider outage không mất ingestion/canonical data | complete remote run không phụ thuộc provider; failed/partial guard giữ lifecycle | Pass |
| Semantic giữ status/source filter/model compatibility | API/OpenAPI/embedding compatibility join smoke pass | Pass |
| Trend demo có denominator và meaningful analyzed cohort | `cohortSize=3339`, `analyzedJobs=1003`, `coverage=0.3004` | Pass |

## 6. Verification evidence

| Gate | Kết quả |
|---|---|
| Full suite với PostgreSQL thật | `206 passed in 34.35s` |
| Default suite không database | `177 passed, 28 skipped` |
| Ruff | check pass; format `149 files already formatted` |
| mypy | `76 source files`, no issues |
| pip check | No broken requirements |
| Compose | `config --quiet` pass; API rebuilt and healthy |
| Docker image | `devradar-app:local` rebuilt from current source/lock/model layers |
| Security/privacy | no raw JD/CV/query/vector/secret in logs/evidence; task board và `.env.local` ignored |

## 7. Handoff

V3 đã đủ điều kiện đóng và push. V4-001 được mở ở trạng thái `Ready` để chốt deterministic baseline/tool policy trước khi cân nhắc LangGraph; không tự thêm dependency V4 vào V3 image.
