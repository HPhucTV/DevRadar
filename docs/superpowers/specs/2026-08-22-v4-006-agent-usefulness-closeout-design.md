# V4-006 Agent usefulness comparison và closeout — Design Spec

**Ngày:** 2026-08-22  
**Trạng thái:** Đã được user ủy quyền quyết định và xác nhận tiếp tục  
**Phase:** V4 — Agentic decision layer

## Mục tiêu

V4-006 quyết định giữ hoặc loại từng reasoning path `planner`, `validator` và `analyst` bằng evidence hiện có, sau đó đóng V4 mà không biến scripted workflow correctness thành model usefulness claim.

Kết quả thiết kế là loại runtime agent thử nghiệm. Deterministic V1–V3 workflows vẫn là production path; ADR, spec và evidence V4 được giữ làm lịch sử đánh giá. Không gọi live provider, không gửi JD/CV/raw HTML ra ngoài, không thêm dependency, API hoặc hạ tầng.

## Các hướng đã cân nhắc

### 1. Chạy live DeepSeek trên safe facts

Rejected. ADR-008 chỉ chấp nhận DeepSeek cho synthetic extraction spike, nên V4 cần ADR/privacy/evaluation boundary mới. Quan trọng hơn, safe facts hiện đã chứa exact policy outcome, validation result, trend direction và caveat. Model chỉ có thể lặp lại kết quả deterministic hoặc bị application gate reject; không có frozen label cho priority/delay hay operator outcome để chứng minh usefulness mới. Live call chỉ đo khả năng bắt chước, latency và cost.

### 2. Giữ provider-neutral scaffolding để dùng sau

Rejected. Không có production provider, caller, public API hoặc measured need. Giữ decision schema, proposal loop, run state, persistence và bảng audit chỉ vì có thể dùng trong tương lai trái phase gate và để lại một runtime surface không có consumer.

### 3. Loại runtime agent, giữ lịch sử đánh giá

Accepted. Đây là cách duy nhất đáp ứng rule V4-001: responsibility chỉ được giữ khi cải thiện usefulness/accuracy mà không regression safety. Code thử nghiệm, test chỉ phục vụ code đó và schema `agent_runs` bị loại; ADR/evidence cũ tiếp tục giải thích điều gì đã được thử và vì sao bị loại.

## So sánh theo responsibility

Safety metric V4-001 đã ở trần: decision schema `100%`, policy violation `0`, planner safety outcome `100%`, validator unsupported-evidence acceptance `0`, analyst query/cohort/denominator `100%` và unsupported aggregate claim `0`. Scripted proposal pass không thể tăng các metric này.

| Responsibility | Dữ liệu proposal nhận | Outcome authoritative hiện tại | Khoảng trống usefulness có label | Quyết định |
|---|---|---|---|---|
| `planner` | schedule/retry/quarantine permission đã tính | V2 schedule, retry cap và source health policy | Không có label chứng minh priority/delay cải thiện freshness, reliability hoặc operator effort | Loại |
| `validator` | schema/evidence validity, safe issue code và retry eligibility đã tính | V3 deterministic schema/evidence/canonicalization | Không có raw evidence hợp lệ để reasoning thêm; accept/reject/retry đã được xác định | Loại |
| `analyst` | exact query/metric refs, direction và required caveat đã tính | V3 aggregate cùng V4-005 deterministic projection | Không còn claim field nào model được phép tạo tự do; output hợp lệ chỉ lặp lại projection | Loại |

Không gán điểm usefulness giả khi chưa có dataset/label. Kết luận kiểm chứng được là **không có measurable gain đủ điều kiện để giữ**; theo exit rule, responsibility bị loại.

## Thay đổi kiến trúc

### Runtime code

Xóa toàn bộ package `devradar.agents`, gồm:

- decision/policy/application contract;
- safe responsibility fact builders;
- proposal request/attempt và direct workflow;
- typed run state, persistence operation và ORM `AgentRun`.

Các module này không có consumer ngoài test V4 và Alembic metadata import. Không chuyển chúng sang `intelligence`, không tạo wrapper hoặc feature flag. Deterministic source health, extraction validation và analytics vẫn ở module sở hữu hiện tại.

### Database

Không sửa migration `f4a6c2d8e901` đã commit. Thêm một revision kế tiếp:

- `upgrade()` drop bảng `agent_runs` cùng dữ liệu thử nghiệm của bảng;
- `downgrade()` tái tạo đúng schema/index/constraint của revision trước nhưng không thể khôi phục row đã xóa;
- bỏ agent model khỏi `migrations/env.py`, để metadata tại head khớp schema không có `agent_runs`.

`agent_runs` không chứa Job, snapshot, extraction, embedding, CV hoặc dữ liệu domain authoritative. Migration vẫn được coi là destructive trong evidence và phải được kiểm tra bằng upgrade/downgrade/upgrade trên PostgreSQL thật.

### Test

Xóa test chỉ kiểm proposal, policy, AgentRun và workflow đã bị loại. Thêm migration regression nhỏ vào PostgreSQL schema suite:

- upgrade tới revision tạo bảng để chứng minh historical step còn hợp lệ;
- upgrade head để chứng minh bảng bị drop;
- downgrade một revision để chứng minh schema có thể tái tạo;
- upgrade head lần nữa và chạy Alembic drift check.

Sau đó chạy full default/PostgreSQL suite, Ruff, format, mypy, pip check và Markdown link validation. Không giữ test “module không import được”; absence được kiểm tra bằng final source/reference scan.

## Tài liệu và decision history

Thêm ADR-013 để supersede phần “giữ direct V4 agent workflow” của ADR-012. ADR-012 vẫn authoritative cho kết luận hoãn LangGraph và giữ nguyên evidence spike; ADR-013 authoritative cho việc không có agent runtime hiện hành.

Cập nhật:

- `README.md`, `AGENTS.md`, `docs/AI.md`, `docs/ARCHITECTURE.md`, `docs/DOMAIN_MODEL.md` và `docs/ROADMAP.md`;
- ADR index và V4-006 closeout evidence;
- `TASK_BOARD.md` cục bộ: V4-006 `Done`, V4 `complete`, V5-001 `Ready`.

V4 demo evidence được mô tả là historical spike/evaluation, không phải capability đang chạy. V5 không được phép tái sử dụng agent code đã loại; nếu xuất hiện use case reasoning có labeled usefulness target mới, phải có ADR/evaluation plan mới trước implementation.

## Failure và security boundary

- Không gọi DeepSeek hay provider khác trong V4-006; `.env.local` không được đọc hoặc log.
- Không thay đổi deterministic workflow V1–V3 hoặc public `/api/v1` contract.
- Không xóa migration/evidence cũ để che lịch sử.
- Không để import, ORM metadata, test, docs hoặc task claim nói `AgentRun`/agent runtime vẫn active sau closeout.
- Migration drop chỉ tác động `agent_runs`; downgrade không tuyên bố phục hồi dữ liệu đã drop.

## Definition of Done

- ADR-013 ghi rõ comparison, keep/delete decision và reconsideration gate.
- Không còn runtime/import/test consumer của `devradar.agents` hoặc current `AgentRun` model.
- PostgreSQL head không có `agent_runs`; migration historical round-trip và `alembic check` pass.
- Full default/PostgreSQL/static/dependency/Markdown gates pass.
- V4 exit criteria được map sang evidence: safety/failure gates đã chứng minh ở V4-001–V4-005, usefulness không có measurable gain nên cả ba feature bị loại.
- Roadmap chuyển V4 sang `complete`; V5 vẫn `proposed`, V5-001 chỉ chuyển `Ready` trên task board cục bộ.
- Git final diff không chứa dependency, API, graph/provider runtime hoặc unrelated cleanup.

