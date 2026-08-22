# V5-004 JobMatch scoring và evaluation — Design Spec

**Ngày:** 2026-08-23

**Trạng thái:** Được triển khai theo quyền tự quyết và tự động thực hiện task kế tiếp mà user đã cấp

**Phase:** V5 — Dashboard, CV matching và alerts

## Mục tiêu

Tạo một ranking heuristic deterministic, versioned và giải thích được giữa `ResumeProfile` còn hiệu lực với `Job` active. Hệ thống phải trả component score, matched/missing skills, evidence coverage và version; không mô tả score như xác suất được tuyển, không gửi CV ra external provider và không giữ resume vector.

## Phương án

### Persisted match, compute on demand — chọn

`POST /api/v1/resume-profiles/{profileId}/matches` chạy một bounded synchronous generation, lưu top 100 `JobMatch`; `GET` chỉ đọc current compatible rows có pagination. Cách này giữ GET side-effect free, cho phép kiểm stale/hash/version và hỗ trợ cascade delete.

### Compute toàn bộ trong GET — loại

Ít schema hơn nhưng mỗi read lại gọi embedding model, GET làm công việc mutation-like, không có artifact để kiểm stale/delete và khó phân biệt generation failure với empty result.

### Queue/worker và persisted ResumeProfileEmbedding — defer

Phù hợp khi có concurrent public traffic hoặc model latency đã đo gây áp lực. V5 hiện là single-operator local/protected, model local khoảng 100–200 ms và inventory 3.339 jobs; thêm queue, worker hoặc một embedding entity riêng chưa có measured need.

Không thêm ADR: scoring weights, component và API đều có version, dễ thay bằng version mới mà không đổi topology hoặc dependency. Rationale được khóa trong spec, dataset và evidence V5-004.

## Domain contract

`JobMatch` là derived artifact giữa đúng một `ResumeProfile` và một `Job`. Current identity gồm:

```text
resume_profile_id
+ profile_content_hash
+ profile_parser_version
+ job_id
+ job_content_hash
+ scoring_version
+ profile_embedding_input_version
+ job_embedding_input_schema_version
+ embedding_provider/model/revision/dimension
```

Row cũ không bị diễn giải là current khi Job hash, profile parser/content, scoring version hoặc model identity đổi. `ResumeProfile` deleted/expired không được đọc/generate; xóa profile cascade toàn bộ matches. Job bị xóa cascade matches; Job đổi chỉ làm row cũ stale theo hash join và lần generation mới tạo identity mới.

`JobMatch` persist:

- `overall_score` và `evidence_coverage` trong `[0,1]`;
- nullable `skill_score`, `semantic_score`, `experience_score`, `location_score`, `role_score`;
- bounded canonical `matched_skills`, `missing_skills`;
- deterministic `explanation`, không chứa raw CV/JD;
- profile/job hash, profile/job embedding schema, scoring/model version/dimension và `created_at`.

Không persist profile vector, raw profile text, Job description, owner token/hash trong `JobMatch` hoặc response.

## `scoring-v2`

Weights được chọn sau development comparison và tổng bằng `1.00`:

| Component | Weight | Cách tính |
|---|---:|---|
| `skill` | `0.40` | Latest current accepted `ExtractionResult`. Required/preferred/optional-or-mentioned có weight `3/2/1`; score là matched weight / total weight. |
| `semantic` | `0.25` | Cosine similarity giữa structured profile embedding và current compatible Job embedding, clamp vào `[0,1]`. |
| `experience` | `0.15` | Khi có profile years và job minimum: `1` nếu profile đạt minimum, ngược lại `profile/minimum`; max years không làm giảm score. |
| `location` | `0.10` | Exact canonical overlap giữa profile location evidence và Job city/province. Đây là evidence overlap, không phải cam kết relocation. |
| `role` | `0.10` | Exact overlap giữa profile role family và role deterministic từ Job title. Ambiguous/unknown role không tự match. |

Giả thuyết ban đầu dùng `level`; V2 scoring giữ `role` vì ResumeProfile có role evidence nhưng không có level/preference đáng tin cậy. Experience đã bao phủ seniority định lượng; không suy level từ số năm. Future explicit level preference cần parser/profile contract mới và `scoring-v3`.

Missing component có value `null`, đóng góp `0` vào overall và không được đổi thành neutral/match. `evidence_coverage` là tổng weight của component có value. Công thức:

```text
overall = sum(component_value * component_weight)
coverage = sum(component_weight where component_value is available)
```

Không renormalize khi thiếu component vì semantic-only result không được phép trông như full-evidence match. Score và component được round half-up đến bốn chữ số. Stable order là `overall_score desc`, `job_id asc`; `evidence_coverage` được trả để giải thích độ đầy đủ nhưng không thay đổi tie-break runtime.

`matched_skills`/`missing_skills` chỉ lấy từ accepted current extraction và giữ canonical lowercase taxonomy name. Unknown/malformed extraction làm skill component unavailable, không echo value lỗi. Explanation được render từ allow-listed labels/status, ví dụ nêu số skill matched/missing, component unavailable và caveat location; không dùng LLM.

## Structured profile embedding

Input local model được tạo chỉ từ `ResumeProfile` structured fields theo thứ tự cố định:

```text
Roles: ...
Skills: ...
Experience years: ...
Locations: ...
```

Danh sách sort/deduplicate, text tối đa 2.000 ký tự và không có filename/hash/owner/raw text. Dùng fixed local MiniLM identity đã Accepted ở ADR-010; inference local-files-only, không download/fallback external. Vector chỉ sống trong memory cho một generation rồi bị bỏ.

Profile input version là `resume-match-embedding-input-v2`; Job vector phải giữ exact `job-embedding-input-v2` + provider/model/revision/dimension hiện hành. Model là symmetric multilingual MiniLM không dùng query/passage prefix; runtime gọi bounded local passage embedding cho profile text để không vượt query input cap 300 ký tự.

Generation xét toàn bộ Job `active` có current compatible `JobEmbedding`; exact cosine chạy trong PostgreSQL. Job thiếu vector bị đếm `unavailableJobs` và không được đưa vào top 100. Latest accepted ExtractionResult chỉ bổ sung structured component; thiếu extraction không loại Job vì semantic vẫn là evidence.

## API contract

Cả hai endpoint dùng `DEVRADAR_CV_LOCAL_ENABLED` và required `X-DevRadar-Owner` như V5-003. Cross-owner/deleted/expired profile trả generic `404`; không nhận URL, raw text, weight, model hoặc arbitrary filter.

### POST `/api/v1/resume-profiles/{profileId}/matches`

Không có request body. Success `200`:

```json
{
  "data": {
    "profileId": "uuid",
    "scoringVersion": "job-match-scoring-v2",
    "consideredJobs": 3339,
    "availableJobs": 3339,
    "unavailableJobs": 0,
    "storedMatches": 100,
    "createdMatches": 100,
    "reusedMatches": 0,
    "generatedAt": "2026-08-23T00:00:00Z"
  }
}
```

Replay cùng current identities trả cùng match rows; count `reusedMatches` tăng thay vì duplicate. Model unavailable trả safe `503 embedding_model_unavailable`; zero compatible job trả success với counts zero, không bịa matches.

### GET `/api/v1/resume-profiles/{profileId}/matches`

Nhận `page`/`pageSize` và optional `minScore` `[0,1]`; unknown parameter trả `422`. Chỉ trả current rows của active profile, fixed sort và pagination envelope. Mỗi item gồm:

- `id`, `jobId`, `overallScore`, `evidenceCoverage`;
- object `components` với năm nullable score;
- `matchedSkills`, `missingSkills`, deterministic `explanation`;
- `scoringVersion`, `embeddingModel`, `embeddingRevision`, `createdAt`;
- bounded Job summary: title, company, location, levels, status và canonical source URL.

API không trả profile/job hash, vector, ExtractionResult payload, owner hash/token hoặc raw CV/JD.

## Transaction và idempotency

1. Đọc active owner-scoped profile, copy structured facts/hash/version rồi đóng transaction.
2. Embed structured profile ngoài DB transaction.
3. Trong transaction mới, re-check active profile và query current active Job/embedding/extraction facts.
4. Score/sort bounded rows, insert top 100 bằng PostgreSQL conflict-safe logical key.
5. Commit rồi trả generation summary; event nếu thêm chỉ được chứa profile ID, scoring version và bounded counts.

Nếu Job đổi sau query, stored row mang old hash và tự biến stale vì GET/current generation luôn join exact `Job.job_content_hash`. Nếu profile bị delete/expire trước persistence, generation fail generic `404` và không lưu row.

## Evaluation

Tạo một project-authored synthetic dataset, không chứa CV/JD thật hoặc PII:

- version `job-match-eval-v1`, schema `job-match-eval-schema-v1`;
- 4 development profile groups và 8 held-out groups;
- mỗi group có tối thiểu 3 candidate với relevance label `0..3` và risk tags;
- coverage bắt buộc: missing skill/extraction/location/experience/role, semantic conflict, sparse evidence, overqualified experience, bilingual profile/job và deterministic tie.

Development split so sánh tối thiểu ba weight sets trên cùng năm component khả dụng: skill-heavy, semantic-heavy và balanced role-aware được đề xuất. Held-out chỉ chạy sau khi dataset/version/hash và recommended weights đã khóa.

Release gates:

- held-out Top-1 accuracy `>=0.875`;
- MRR `>=0.90`, NDCG@5 `>=0.90`;
- score/component range, stable tie và monotonicity `100%`;
- missing component/coverage behavior `100%`;
- matched/missing skill evidence closure `100%`;
- unsupported skill/claim rate `0`.

Metrics chỉ đánh giá ranking heuristic trên synthetic labels, không phải hiring outcome hoặc fairness claim. Không dùng protected attributes; không tự động reject/apply candidate.

## Security, privacy và operations

- CV/JD là untrusted; scoring chỉ nhận validated structured facts và numeric similarity.
- Không external model, network, prompt, free-form generation hoặc model-selected action.
- API/event/error không chứa raw CV/JD, vector, owner/hash hoặc malformed extraction value.
- Generation bounded 3.339 current jobs/top 100 stored; timeout/queue chỉ thêm sau measured need.
- Profile deletion cascade và expiry visibility được PostgreSQL/API tests chứng minh; physical purge vẫn thuộc protected-demo cleanup V5-005/V5-007.
- Public exposure vẫn chờ V6 auth/rate-limit/resource hardening.

## Definition of Done

- Synthetic dataset/version/hash, development comparison và held-out report đạt gates trước khi nhận `job-match-scoring-v2`.
- Pure scoring tests khóa component, missing, coverage, monotonicity, stable tie và explanation evidence.
- Migration/model tests khóa range, unique identity, stale hash và cascade delete trên PostgreSQL thật.
- POST/GET OpenAPI + owner/gate/404/503/422/pagination/idempotency tests pass.
- Local model/pgvector integration chứng minh structured profile input, exact compatible embedding và top-100 persistence mà không external network.
- `docs/API.md`, `docs/AI.md`, `docs/DOMAIN_MODEL.md`, `docs/ARCHITECTURE.md`, roadmap/evidence và ignored task board đồng bộ; default/PostgreSQL/static/Compose/Markdown/security gates pass.
