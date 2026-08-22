# V3-005 — Local embeddings, semantic search và skill trends

## 1. Kết quả

**Status:** `complete` cho task V3-005 ngày 2026-08-22. Phase V3 đã `complete` sau [V3-006 closeout](V3-006-v3-closeout.md); evidence này ghi contract/runtime của embedding/search/trend layer.

Các số liệu runtime trong bảng bên dưới là baseline của lần V3-005 ban đầu với E5; model identity hiện hành và semantic remediation được kiểm chứng riêng tại [V3-006 closeout evidence](V3-006-v3-closeout.md) theo ADR-010.

Implementation ban đầu theo [ADR-009](../decisions/0009-accept-local-multilingual-e5-and-pgvector.md), sau đó được cập nhật theo [ADR-010](../decisions/0010-accept-fastembed-minilm-semantic-remediation.md), đã thêm:

- fixed-revision local `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` qua FastEmbed `0.8.0`, dimension 384, không prefix và artifact SHA-256 validation;
- `job_embeddings` derived table trên pgvector `0.8.6`, logical model/hash identity và exact cosine query;
- explicit `download-embedding-model` cùng bounded `embed-jobs --max-items 1..1000` operator commands;
- additive `query`, `searchMode`, `skill` và nullable `relevanceScore` trên `GET /api/v1/jobs`;
- `GET /api/v1/skills` và `GET /api/v1/skill-trends` với Job cohort denominator, analyzed coverage và stable ordering;
- container model prefetch, local-files-only inference và ONNX Runtime telemetry disabled trước initialization.

Không thêm external embedding API, HNSW, `Skill`/`JobSkill` materialized tables, Redis, queue, distributed worker hoặc public auth/rate limit.

## 2. Model và privacy boundary

Fixed identity:

```text
provider             local_fastembed
model                sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
artifact source      qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q
revision             faf4aa4225822f3bc6376869cb1164e8e3feedd0
input schema         job-embedding-input-v2
dimension            384
database             pgvector 0.8.6 / PostgreSQL 18
search               exact cosine, no HNSW
```

Operator download lấy đúng năm required artifact từ revision trên. Loader kiểm SHA-256 trước khi khởi tạo ONNX Runtime; inference không download trong API request. Query tối đa 300 ký tự, canonical Job input tối đa 12.000 ký tự. Vector sai dimension/non-finite, artifact thiếu/sai hash hoặc model lỗi đều fail closed; semantic API trả safe `503` và không fallback external.

Raw query, JD, vector, model path và artifact content không nằm trong API/log/evidence. Docker image đặt `ORT_DISABLE_TELEMETRY=1`; smoke dưới read-only filesystem không tạo telemetry identifier hoặc warning. Official behavior được đối chiếu từ [FastEmbed 0.8.0](https://pypi.org/project/fastembed/0.8.0/), [FastEmbed supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/), [MiniLM model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2), [pgvector](https://github.com/pgvector/pgvector), [pgvector-python SQLAlchemy](https://github.com/pgvector/pgvector-python#sqlalchemy) và [ONNX Runtime privacy](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md#disabling-telemetry).

## 3. Persistence và API contract

`job_embeddings` dùng `vector(384)` và unique logical key:

```text
job_id + input_hash + input_schema_version
+ provider + model + model_revision
```

Backfill chọn Job thiếu current compatible row, đọc canonical text trong transaction ngắn, gọi model ngoài transaction, rồi re-check `job_content_hash` trước insert. Concurrent/replay winner trở thành cache hit; Job đổi hash trong lúc inference tăng `stale_skipped` và không persist stale result.

Semantic search chỉ join đúng current Job hash/input schema/provider/model/revision/dimension. Status/source/skill conditions được áp trước exact cosine order; Job ID là tie-break. `relevanceScore = 1 - cosine_distance`, bounded `[-1, 1]`, chỉ là ranking similarity.

Skill analytics đọc latest accepted `ExtractionResult` đúng current Job hash, extraction schema và canonicalization version. `cohortSize` luôn là toàn filtered Job cohort; missing/rejected/stale extraction chỉ giảm `analyzedJobs`/coverage. Skill share dùng cohort denominator và mỗi skill chỉ được đếm một lần trên mỗi Job. Trend window inclusive tối đa 366 ngày, top skill tối đa 20.

## 4. Verification evidence

Các command dưới đây chạy trên Windows PowerShell, Python `3.13.14`, Docker Engine hiện có và PostgreSQL Compose thật.

| Gate | Kết quả |
|---|---|
| Narrow embedding/search/analytics/CLI tests | `21 passed` |
| Full suite với `DEVRADAR_TEST_DATABASE_URL` | `191 passed in 49.91s`; PostgreSQL-marked tests không skip |
| PostgreSQL schema | extension `0.8.6`, column `vector(384)`, logical uniqueness/current-hash/idempotency/rollback tests pass |
| Alembic | `upgrade head`, `current=c82f4a7d901e`, `check` không có operation mới; offline SQL sinh extension/table/index đúng thứ tự |
| Fixed model download | 5 artifact tải từ exact ONNX revision; application integrity check pass |
| Local model smoke | cold integrity/load `6.402s`; hai synthetic embeddings `0.063s`; dimension 384 và finite |
| Local backfill smoke | `selected=1`, `created=1`, `cache_hits=0`, `stale_skipped=0` |
| Local API smoke | semantic Job `200`, 2 current embedded result có score; skills `200` |
| OpenAPI | 10 paths; có `/skills`, `/skill-trends`, `query`, `searchMode`, `skill` và bounded trend params |
| Static/dependency gates | Ruff check pass; 138 files format-clean; mypy 72 source files pass; `pip check` không broken requirement |
| Compose/migration config | crawler-profile Compose config pass; `git diff --check` pass |
| Docker image | cold build pass; `devradar` user; 706,904,766 bytes; read-only/cap-drop model smoke `6.820s`, dimension 384 finite, exit 0 |
| Container telemetry | `ORT_DISABLE_TELEMETRY=1` trong image; read-only smoke không còn persistent-device warning |
| Internal Markdown links | Project/Git Markdown checker pass sau khi evidence được thêm |

Hash-locked runtime thêm đúng `fastembed==0.8.0` và `pgvector==0.5.0`; clean install từ `requirements-dev.lock` đã được kiểm trước final gates. `.dockerignore` loại model cache/local artifacts khỏi build context; model chỉ nằm trong ignored local data hoặc fixed image layer.

## 5. Live-data boundary và V3 handoff

Local project database hiện có 3339 canonical Job từ approved complete runs. Semantic API chỉ rank Job đã backfill compatible embedding; current coverage là `3339/3339`. Skill/trend API trả đúng denominator và analyzed coverage:

```text
cohortSize      3339
analyzedJobs    1003
coverage        0.3004
```

Đây là analyzed cohort có denominator; các job thiếu evidence vẫn giữ `needs_review` và không bị đưa vào skill count. Full phase gate, source/cohort boundary, semantic held-out và provider-independence nằm trong [V3-006 closeout](V3-006-v3-closeout.md).
