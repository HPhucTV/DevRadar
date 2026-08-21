# ADR-002: Data pipeline trước AI và agentic workflow

## Status

Accepted

## Date

2026-08-21

## Context

Giá trị của trend, matching và agent phụ thuộc vào dataset đúng, có provenance và có lịch sử. LLM có thể trích xuất JD phi cấu trúc nhưng cũng tạo hallucination, cost, latency và failure mode khó tái hiện. Agent không thể sửa một pipeline không biết run complete hay partial, identity không ổn định hoặc không giữ raw evidence.

## Decision

- V1–V2 hoàn thành deterministic ingestion, normalization, source-scoped identity, idempotency, change detection và observability trước.
- Extraction order là structured data/API → source parser/selector → LLM fallback.
- LLM bắt đầu ở V3 sau khi có labeled evaluation dataset, schema/evidence validation và cost/privacy baseline.
- Agentic workflow bắt đầu ở V4, ban đầu chỉ cho planner, validator và analyst responsibilities có reasoning thật.
- Deterministic application layer sở hữu persistence, authorization, retry limit và state transition. Model/agent chỉ trả typed proposal/decision.
- Ingestion vẫn hoạt động khi AI provider không sẵn sàng; AI-only field có trạng thái partial/pending/review rõ.

## Alternatives considered

### LLM parse toàn bộ JD ngay từ V1

Rejected vì structured data và selector thường nhanh/rẻ/dễ debug hơn; cách này cũng thiếu evaluation dataset để biết output đúng đến đâu.

### LangGraph điều phối toàn pipeline từ đầu

Rejected vì scheduling, retry, persistence và state transition là workflow xác định. Agent ở các bước này tăng nondeterminism mà chưa có decision quality để đo.

### Không dùng AI

Rejected cho tầm nhìn dài hạn vì JD/CV phi cấu trúc và insight/explanation có use case hợp lý khi deterministic extraction không đủ. AI vẫn được giữ sau gate, không bị loại hoàn toàn.

## Consequences

### Positive

- V1 có thể test/replay mà không cần provider/network AI;
- AI quality được đo trên cùng evidence thay vì đánh giá cảm tính;
- cost, prompt/model regression và failure không làm hỏng canonical ingestion;
- câu trả lời phỏng vấn về “tại sao cần agent” dựa trên boundary thật.

### Trade-offs

- demo AI xuất hiện muộn hơn;
- một số field sẽ còn `null`/partial ở V1–V2;
- cần đầu tư fixture, provenance và labeled evaluation trước V3.

### Required follow-up

- V3 phải ghi baseline/target evaluation trước khi model output ảnh hưởng canonical data.
- V4 phải so sánh agent với deterministic baseline; responsibility không cải thiện metric sẽ không trở thành agent riêng.

