# V3-006 — Evaluation, scale và V3 closeout

## 1. Kết luận

**Status:** `blocked` ngày 2026-08-22. V3 vẫn `in_progress`; V4 chưa được mở và repository chưa được push.

Hai release gate độc lập chưa đạt:

1. approved complete inventory có `78/500` canonical Job, thiếu `422`;
2. fixed semantic held-out chưa đạt Top-1, MRR và cross-language target đã khóa trước live run.

Không dùng fixture/partial run để tăng count, không hạ threshold, không tự cấp waiver, không sửa held-out sau khi thấy metric và không crawl source ngoài allow-list. Extraction analytics trên data thật hiện có coverage `0/78 = 0.0`, nên cũng chưa có trend evidence đủ để demo.

## 2. Fixed semantic evaluation

Dataset được commit trước live evaluation:

```text
dataset       semantic-retrieval-eval-v1
schema        semantic-retrieval-eval-schema-v1
SHA-256       60b9b017c7c2fed1d8d15956ad46c3c7f6206229190734d58a5e03c7b62349ef
provenance    project-authored-synthetic-no-third-party-content
documents     12
held-out      24 queries: vi=12, en=11, mixed=1
cross-lang    10 queries
```

Target được ghi trong [V3-006 design](../superpowers/specs/2026-08-22-v3-006-evaluation-scale-closeout-design.md) trước khi chạy model. Fixture không thay đổi sau live run.

| Metric | Target | Observed | Gate |
|---|---:|---:|---|
| Top-1 accuracy | `>=0.9000` | `0.7917` | Fail |
| MRR | `>=0.9500` | `0.8819` | Fail |
| Recall@5 | `1.0000` | `1.0000` | Pass |
| Cross-language Top-1 | `>=0.8500` | `0.5000` | Fail |
| Dimension/finite | 384/all finite | 384/true | Pass |
| Monetary model cost | report actual | `USD 0` local | Pass |

Fixed model vẫn là `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`. Live evaluation passage p50/p95 là `134.222/212.825 ms`; query p50/p95 `99.455/120.207 ms`. Đây là baseline trên máy local, không phải production SLO.

Không chỉnh query/label hoặc thêm post-hoc hybrid weight theo held-out failures. Remediation cần model/retrieval spike mới với development-only tuning, fixed held-out version mới và ADR nếu đổi model/dimension/provider.

## 3. Approved-source full refresh

Ba source exact allow-list được chạy sequentially bằng sandboxed Compose `crawler`, không dùng `--max-items`:

| Source | Run ID | Status/coverage | Found | Failed/new/updated/missing/removed | Duration |
|---|---|---|---:|---|---:|
| NAVER Vietnam/Greenhouse | `dabd4392-98d6-4366-b757-ae283fdd6cf6` | `succeeded/complete` | 14 | `0/0/0/0/0` | 2.658 s |
| VNG Careers | `97f3b066-8c6c-440a-9357-357bf20a1ec9` | `succeeded/complete` | 27 | `0/0/0/0/0` | 352.086 s |
| MoMo Careers | `5c74a7fc-65fc-4bab-8f61-2f4f59181761` | `succeeded/complete` | 37 | `0/0/0/0/0` | 212.169 s |

Mọi observation đều `unchanged`; không có false missing/removal. Current canonical inventory:

```text
MoMo Careers                          37
NAVER Vietnam Careers via Greenhouse 14
VNG Careers                           27
Total                                 78
Gate                                 500
Gap                                  422
```

Count chỉ dùng complete runs trên source approved. GeoComply/Lever vẫn `permission_required`; không được dùng để lấp gap.

## 4. Embedding, exact search và analytics baseline

Backfill current model/hash đã tạo 76 row còn thiếu; immediate rerun trả `selected=0, created=0`, không stale. Current compatible coverage là `78/78`.

| Metric | Observed |
|---|---:|
| Persisted passage latency p50/p95 | `169.5/224.9 ms` |
| Fixed model files | 13 files, `487,360,593` bytes (`464.78 MiB`) |
| Docker application image | `706,904,766` bytes (`674.16 MiB`) |
| `job_embeddings` total relation | `248 KiB` |
| Exact PostgreSQL top-20 execution | `3.791 ms`, 39 shared buffer hits |
| Semantic API cold | `8009.573 ms`, HTTP 200 |
| Semantic API warm p50/p95, 20 calls | `50.153/60.919 ms`, toàn bộ HTTP 200 |
| Warm result count | 20/20 page items ổn định |
| HNSW/external vector store/cache | Không thêm; chưa có measured need |

Exact query dùng sequential scan/top-N trên 78 compatible vector; kết quả này không đủ để ngoại suy cho 500+ hoặc public concurrency, nhưng cũng không tạo bằng chứng cần HNSW ở workload hiện tại.

Skill/trend API trả đúng honest boundary:

```text
cohortSize      78
analyzedJobs     0
coverage       0.0
trendBuckets     1 (denominator only, no invented skill)
```

Không gửi 78 source JD tới DeepSeek vì ADR/source privacy boundary hiện chỉ cho synthetic generation spike. Không thêm production provider adapter để làm đẹp coverage.

## 5. V3 exit-criteria audit

| Roadmap criterion | Evidence | Status |
|---|---|---|
| `>=500` canonical Job từ approved/reproducible runs | Ba complete refresh; `78`, gap `422` | Blocked |
| Accuracy/hallucination/review/cost đạt held-out target | Extraction held-out V3-002 đạt; semantic fixed held-out fail 3/4 quality target | Blocked |
| Structured parser đủ dữ liệu không gọi LLM | V3-003 tests và targeted failure suite | Pass |
| Malformed/injected output bị chặn | V3-001/V3-003/V3-004 regression tests | Pass |
| Model/prompt/schema/cache versioning | Extraction/embedding/evaluation identity và regression tests | Pass |
| Provider outage không mất ingestion/canonical data | 5 targeted tests pass; three live crawl runs độc lập model/provider | Pass |
| Semantic giữ status/source filter và model compatibility | V3-005 PostgreSQL/OpenAPI tests | Pass |
| Trend demo có denominator và meaningful analyzed cohort | Denominator đúng nhưng analyzed coverage `0.0` | Blocked |

## 6. Verification

| Gate | Kết quả |
|---|---|
| Semantic dataset/evaluator TDD | RED import failure; GREEN `6 passed` |
| Full suite với PostgreSQL thật | `197 passed in 45.30s`; không skip PostgreSQL gate |
| Provider/model failure independence | `5 passed in 7.92s` |
| Ruff | check pass; 143 files format-clean |
| mypy | 74 source files, no issues |
| `pip check` | No broken requirements |
| Alembic | `current=c82f4a7d901e`; no drift; offline SQL pass |
| Compose/OpenAPI | crawler profile config pass; 10 paths và V3 params present |
| Docker build | Pass từ current source/locks, fixed model/browser layers cached |
| Secrets/privacy | Không report prompt/JD/query/vector/key; `.env.local`, model/data và task board vẫn ignored |

## 7. Điều kiện mở khóa

V3-006 chỉ được resume khi có cả hai workstream được phê duyệt:

1. **Inventory:** approved-source inventory tăng lên 500 qua complete runs, hoặc user phê duyệt source-discovery/adapter work riêng cho nguồn mới vượt đầy đủ terms/robots/rate-limit/stability/test gate.
2. **Semantic quality:** model/retrieval remediation được thiết kế bằng development split, khóa dataset held-out version mới trước live run và ghi ADR mới nếu thay model/dimension/provider.

Sau đó phải backfill extraction/embedding, rerun fixed gates, chứng minh analytics coverage và chạy lại toàn bộ closeout matrix. Cho tới lúc đó không push Phase V3 và không triển khai V4 chỉ để né blocker.
