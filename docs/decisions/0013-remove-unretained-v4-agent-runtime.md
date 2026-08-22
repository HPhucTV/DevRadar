# ADR-013: Loại V4 agent runtime không chứng minh measurable usefulness

## Status

Accepted — supersedes phần direct planner/validator/analyst runtime của ADR-012. ADR-012 vẫn giữ quyết định defer LangGraph.

## Date

2026-08-22

## Context

V4-001 đặt rule trước khi implementation: một responsibility agent chỉ được giữ nếu cải thiện usefulness hoặc accuracy so với deterministic baseline mà không regression safety. Nếu không, feature phải bị loại. V4-002 chọn direct workflow thay vì LangGraph; V4-003–V4-005 sau đó xây typed run state, `AgentRun`, safe facts và provider-neutral proposal workflow cho `planner`, `validator` và `analyst`.

Các test này chứng minh schema, policy, limits, persistence và fallback hoạt động với scripted proposal callable. Chúng không chứng minh model usefulness. Repository không có production provider/caller/API cho workflow, và ADR-008 chỉ cho phép DeepSeek ở synthetic extraction spike.

Comparison V4-006 cho thấy proposal input đã chứa outcome authoritative:

| Responsibility | Deterministic authority | Phần proposal còn lại | Measurable gain |
|---|---|---|---|
| `planner` | V2 schedule/retry cap/source health và quarantine policy | chọn priority/delay từ permission đã tính | Không có frozen label về freshness, reliability hoặc operator effort |
| `validator` | V3 schema/evidence/canonicalization và retry eligibility | chọn accept/reject/retry từ validity đã tính | Không có evidence mới để model reasoning; divergence bị gate reject |
| `analyst` | V3 aggregate cùng V4-005 exact direction/caveat projection | lặp lại claim/query/metric/direction/caveat | Không còn field usefulness nào model được phép tạo tự do |

Safety metric V4-001 đã ở trần hoặc zero-error gate: schema validity `100%`, policy violation `0`, planner deterministic outcomes `100%`, validator unsupported-evidence acceptance `0`, analyst valid evidence `100%` và unsupported aggregate claim `0`. Scripted model output khớp deterministic facts không thể cải thiện các metric này. Không có labeled usefulness dataset nào cho outcome còn lại, nên không được gán gain giả hoặc dùng live provider để đo khả năng bắt chước.

## Decision

- Loại cả ba reasoning path `planner`, `validator` và `analyst`.
- Giữ V1–V3 deterministic workflows làm authoritative production path.
- Xóa package `devradar.agents`, test chỉ phục vụ package đó và bảng `agent_runs` bằng một migration kế tiếp.
- Giữ ADR, design spec, implementation plan và evidence V4 làm historical evaluation record; không sửa migration/ADR cũ để che lịch sử.
- Không mở DeepSeek hoặc provider runtime cho V4-006. Không có JD, CV, raw HTML hay safe-fact payload nào được gửi ra external provider.
- Chỉ đánh giá lại agent khi có responsibility mới với frozen labeled dataset, measurable usefulness/accuracy target, privacy boundary và output không deterministic từ input facts. Quyết định mới phải có ADR trước implementation.

Migration drop `agent_runs` là destructive với row audit thử nghiệm. Bảng không chứa Job, snapshot, extraction, embedding, CV hoặc dữ liệu domain authoritative. Downgrade tái tạo schema historical nhưng không thể khôi phục row đã drop; evidence phải ghi rõ boundary này.

## Alternatives considered

### Chạy live DeepSeek trên safe facts

Rejected. Cần mở rộng ADR-008 và privacy/evaluation boundary, nhưng vẫn không tạo comparison hợp lệ vì expected outcome đã nằm trong input. Kết quả chỉ đo imitation, latency và cost.

### Giữ provider-neutral scaffolding để dùng sau

Rejected. Không có current consumer hoặc measured need. Decision schema, proposal loop, run state và persistence sẽ là dead architecture, tăng migration/test/maintenance surface cho khả năng giả định.

### Chỉ loại analyst, giữ planner/validator

Rejected. Planner và validator cũng nhận deterministic permission/validity đã tính, không có labeled model-only usefulness target và không có production caller. Không responsibility nào vượt keep gate.

## Consequences

### Positive

- Current runtime phản ánh capability thật; không có “agent demo” chỉ chạy bằng scripted callable.
- Giảm package, test, ORM/schema và security surface không có consumer.
- Deterministic schedule, validation và analytics giữ nguyên correctness/provenance.
- V5 bắt đầu từ API/data capability đã chứng minh, không phụ thuộc agent abstraction bị defer.

### Trade-offs

- Portfolio không còn runnable V4 agent workflow hoặc `AgentRun` audit table.
- Historical database đã áp revision V4 sẽ drop audit row khi lên head.
- Nếu future use case có reasoning thật, decision/run/audit contract phải được thiết kế lại từ requirement và evaluation mới thay vì tự động phục hồi code cũ.

## Required follow-up

- Thêm Alembic revision drop `agent_runs` và test upgrade/downgrade/upgrade trên PostgreSQL thật.
- Xóa current runtime/import/test consumer và đồng bộ architecture/domain/AI docs.
- V4-006 evidence map safety boundary lịch sử cùng removal decision, rồi chuyển V4 sang `complete` và V5 thành phase kế tiếp.

