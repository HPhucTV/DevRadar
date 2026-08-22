# V3-003 ExtractionResult, deterministic fallback và accepted-only cache — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Đã được user duyệt; implementation plan đã sẵn sàng
**Phase:** V3 — AI extraction, taxonomy và semantic search

## Mục tiêu

Tạo persistence và orchestration contract cho `ExtractionResult` để DevRadar:

- chạy deterministic extraction trước;
- không gọi LLM khi deterministic result đã đủ dữ liệu;
- dùng lại kết quả `accepted` theo content/version cache key;
- giới hạn provider attempts và chuyển lỗi sang `needs_review`/`rejected`;
- không ghi raw JD, prompt, model output hoặc CV vào log/tracing;
- giữ provider call ở một boundary được inject, chưa tạo production DeepSeek adapter.

## Quyết định đã khóa

- PostgreSQL là system of record cho `ExtractionResult`.
- Cache chỉ phục vụ result có `validation_status=accepted`.
- `rejected` và `needs_review` vẫn được lưu để audit nhưng không phải cache hit.
- Cache key thay đổi khi input reference/hash, schema, extractor, prompt, model hoặc canonicalization version thay đổi.
- Deterministic fields có precedence: model không được ghi đè giá trị đã được parser xác định.
- Provider call không chạy trong transaction đang giữ row lock; persistence được thực hiện trong transaction riêng.
- Không thêm SDK, queue, Prefect, Redis, endpoint mới, embedding hoặc production provider adapter trong task này.

## Phạm vi và non-goal

### Trong phạm vi

- SQLAlchemy model và Alembic migration cho `ExtractionResult`;
- typed extraction payload/status/error contract;
- deterministic extractor boundary và completeness decision;
- accepted-only cache lookup/persist;
- bounded provider attempts, validation và safe failure state;
- unit test và PostgreSQL integration test cho transaction/unique cache key;
- cập nhật domain/AI/operations evidence.

### Ngoài phạm vi

- gọi trực tiếp DeepSeek hoặc provider ngoài từ application runtime;
- taxonomy mở rộng, role classification, summary, embeddings và semantic search của V3-004/V3-005;
- public REST endpoint cho extraction;
- retry queue, scheduling hoặc worker mới;
- backfill toàn bộ 78 canonical jobs hiện có;
- cache rejected/needs_review theo TTL.

## Kiến trúc module

| Thành phần | Trách nhiệm |
|---|---|
| `src/devradar/intelligence/models.py` | SQLAlchemy mapping của `ExtractionResult`, enum persistence và accepted-cache partial unique index |
| `src/devradar/intelligence/extraction.py` | Typed contract, deterministic-first orchestration, cache lookup, provider boundary và safe outcome |
| `src/devradar/ingestion/normalization.py` | Reuse parser hiện có cho level, experience, salary, location; không tạo bản sao |
| `src/devradar/intelligence/evaluation.py` | Reuse taxonomy alias vocabulary và schema/evidence semantics của synthetic evaluation |
| `migrations/versions/*_add_extraction_results.py` | Tạo/xóa bảng và index; không backfill dữ liệu cũ |
| `tests/test_extraction.py` | Pure contract, completeness, cache decision và provider failure tests |
| `tests/integration/test_extraction_result.py` | Migration, unique accepted cache, rollback và read-after-write trên PostgreSQL thật |

Không tạo interface provider một implementation. Provider boundary là một callable dependency được inject vào orchestration để test và spike; production adapter sẽ là quyết định riêng sau khi có requirement.

## Domain contract

### ExtractionResult

| Field | Kiểu/giới hạn | Ý nghĩa |
|---|---|---|
| `id` | UUID | Identity của một extraction attempt/result |
| `input_type` | enum hiện tại: `job` | Loại input; CV để phase V5 |
| `input_ref` | UUID | `Job.id` hoặc reference domain tương ứng |
| `input_hash` | 64 lowercase hex | `Job.job_content_hash`, dùng cho cache/replay |
| `extractor_type` | `rule` hoặc `llm` | Đường tạo result |
| `extractor_version` | bounded string | Version deterministic/provider extractor |
| `schema_version` | bounded string | Schema của `output_data` |
| `prompt_version` | nullable bounded string | Có khi dùng provider; `null` cho rule |
| `model` | nullable bounded string | Có khi dùng provider; `null` cho rule |
| `canonicalization_version` | bounded string | Version alias/field canonicalization |
| `output_data` | JSONB | Typed extraction payload đã validate; không raw output |
| `validation_status` | `accepted`, `rejected`, `needs_review` | Trạng thái áp dụng |
| `confidence` | nullable numeric `[0,1]` | Confidence aggregate nếu contract có cung cấp |
| `validation_errors` | nullable JSONB | Safe error code/path/type, không rejected value |
| `latency_ms` | nullable non-negative numeric | Provider/parser metric |
| `prompt_tokens` | nullable non-negative integer | Provider usage |
| `completion_tokens` | nullable non-negative integer | Provider usage |
| `estimated_cost_usd` | nullable non-negative numeric | Estimate, không phải invoice |
| `created_at` | UTC timestamp | Thời điểm persist result |

### Cache key

Cache identity được tạo từ các field sau, theo thứ tự ổn định:

```text
input_type
+ input_ref
+ input_hash
+ extractor_type
+ extractor_version
+ schema_version
+ prompt_version
+ model
+ canonicalization_version
```

Database partial unique index áp dụng cho cache identity của result `accepted`. Các attempt `rejected`/`needs_review` không làm cache key bị chiếm và không được trả về như cache hit. V3-003 cache theo `input_ref`; không reuse result giữa hai Job khác nhau chỉ vì cùng content hash, để giữ provenance rõ ràng.

### Output contract

`output_data` chỉ chứa extraction payload đã qua:

1. object-shape validation;
2. deterministic canonicalization;
3. strict schema/type/range validation;
4. evidence substring validation;
5. domain invariant và policy gate.

Scalar field đã có parser (`levels`, `experience`, `salary`, `location`) lấy từ canonical input. Skill name phải qua taxonomy alias map; alias không hợp lệ hoặc evidence không tồn tại làm result `rejected`/`needs_review` tùy error policy.

## Orchestration flow

```text
Job + content hash
        |
        v
deterministic extractor
        |
        +-- complete --> persist accepted(rule), không gọi provider
        |
        +-- incomplete --> accepted-cache lookup
                              |
                              +-- hit --> return cached result
                              |
                              +-- miss --> provider callable (max 2 attempts)
                                              |
                                              +-- valid --> persist accepted(llm)
                                              +-- invalid/transient exhausted --> persist needs_review/rejected
```

Provider callable nhận input tối thiểu cần thiết và trả untrusted structured candidate. Nó không được nhận URL tùy ý, credential, raw CV hoặc tool capability.

Provider call chạy ngoài transaction dài. Sau khi call xong, transaction persist lại kiểm tra accepted cache lần cuối. Nếu concurrent writer đã tạo cùng accepted key, result hiện có được đọc lại và attempt mới không tạo duplicate accepted record.

## Deterministic completeness

Deterministic extractor trả:

```text
DeterministicExtraction {
  payload: ExtractionPayload
  complete: bool
  extractor_version: str
  warnings: tuple[str, ...]
}
```

`complete=true` chỉ khi mọi field bắt buộc của extraction contract có giá trị hoặc `null` được xác định bởi parser, skill evidence không thiếu và không còn warning cần reasoning. `complete=false` khi còn skill/taxonomy/requirement cần provider hoặc review. V3-004 có thể mở rộng taxonomy nhưng không được đổi precedence deterministic-first.

## Failure và privacy policy

- Missing provider khi result incomplete: persist `needs_review` với safe code `provider_not_configured`.
- Timeout, rate limit hoặc transient provider failure sau bounded attempts: persist `needs_review`, không làm mất deterministic payload.
- Malformed JSON, extra field, enum lạ, evidence thiếu hoặc domain invariant fail: persist `rejected` với error path/type bounded.
- Không retry vô hạn và không retry cùng malformed output không đổi strategy.
- Không log `output_data` đầy đủ nếu có raw text; chỉ log result id, input hash, version, status, error code/path, token/latency/cost.
- `validation_errors` không chứa secret, prompt, JD/CV hoặc rejected value.

## Testing contract

### Unit

- deterministic-complete path không gọi provider và persist `rule/accepted`;
- accepted cache hit không gọi provider lần hai;
- cache key đổi khi input/schema/extractor/prompt/model/canonicalization version đổi;
- rejected/needs_review không được trả như cache hit;
- provider success sau một attempt persist `llm/accepted`;
- transient failure bounded đúng hai attempts rồi `needs_review`;
- malformed shape, extra field, evidence missing và enum invalid bị reject an toàn;
- deterministic fields không bị provider candidate override;
- safe error/metric không chứa raw payload hoặc secret.

### PostgreSQL integration

- migration upgrade/downgrade trên database mới;
- accepted-cache partial unique index và read-after-write;
- concurrent accepted insert không tạo duplicate logical result;
- rollback không để lại nửa result;
- rejected/needs_review rows vẫn audit được nhưng không làm cache hit.

## Definition of Done mapping

- `ExtractionResult` schema/version/cache contract tồn tại và có migration;
- deterministic-complete path được test không gọi provider;
- accepted-only cache hit/miss được test;
- bounded retry/review và malformed/evidence failure được test;
- không có raw prompt/output/JD/CV trong log/error;
- unit và PostgreSQL integration gates pass;
- `docs/DOMAIN_MODEL.md`, `docs/AI.md`, `docs/OPERATIONS.md`, evidence và `TASK_BOARD.md` cập nhật;
- không thêm SDK, queue, Redis, API endpoint hoặc production provider adapter.
