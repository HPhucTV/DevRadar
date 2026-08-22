# V4-002 LangGraph/direct workflow spike — Design Spec

**Ngày:** 2026-08-22
**Trạng thái:** Đã được user xác nhận
**Phase:** V4 — Agentic decision layer

## Mục tiêu

V4-002 trả lời một câu hỏi duy nhất bằng evidence: LangGraph có cung cấp state recovery/resume cần thiết cho DevRadar V4 với giá trị lớn hơn complexity/dependency cost hay direct bounded workflow hiện hữu đã đủ?

Task chạy synthetic local spike và ghi ADR. Nó không triển khai production agent, không gửi job/CV ra model, không tạo `AgentRun`, không đổi public API và không tự chấp nhận framework chỉ vì spike chạy được.

## Bối cảnh đã xác minh

V4-001 đã có `agent-decision-v1`, responsibility-specific typed payload, read-only default-deny tool policy và deterministic application gates. Planner, validator và analyst là ba responsibility độc lập dùng cùng pattern `bounded input → proposal → deterministic validation/application`; chúng chưa tạo một graph nhiều agent phụ thuộc lẫn nhau.

Theo tài liệu chính thức:

- LangGraph `StateGraph` dùng state, node và edge; graph phải compile trước khi invoke: <https://docs.langchain.com/oss/python/langgraph/graph-api>;
- checkpointer lưu checkpoint mỗi graph step và tạo fault tolerance/replay/resume; durability qua process cần persistent checkpointer: <https://docs.langchain.com/oss/python/langgraph/persistence>;
- dynamic interrupt cần checkpointer/thread ID và node chạy lại từ đầu khi resume, nên side effect trước interrupt phải idempotent: <https://docs.langchain.com/oss/python/langgraph/interrupts>;
- official test pattern tạo graph/checkpointer mới cho mỗi test và cho phép test node/partial execution: <https://docs.langchain.com/oss/python/langgraph/test>;
- PyPI ngày 2026-08-22 ghi stable `langgraph==1.2.10`, Python `>=3.10` và có classifier Python 3.13: <https://pypi.org/project/langgraph/>.

Version này chỉ là spike candidate. Nó chưa trở thành runtime contract hoặc Accepted dependency.

## Các hướng đã cân nhắc

### 1. Giữ direct workflow mà không chạy LangGraph

Ưu điểm: không dependency/lock churn, ít code và dễ audit. Nhược điểm: không tạo evidence thực nghiệm cho DoD V4-002 và có thể đánh giá thấp checkpoint/recovery API.

Rejected cho V4-002; direct workflow vẫn là control group.

### 2. Chạy LangGraph trong môi trường cô lập rồi quyết định

Tạo temporary virtual environment/artifact dưới ignored `tmp/`, pin `langgraph==1.2.10`, dùng synthetic typed state và `InMemorySaver`. So sánh cùng workload với direct Python; ghi aggregate result và dependency footprint vào evidence, sau đó xóa/giữ ignored temp artifact tùy nhu cầu local.

Accepted. Cách này kiểm chứng API thật mà không làm runtime lock hoặc image phụ thuộc vào một framework chưa đạt gate.

### 3. Thêm LangGraph và Postgres checkpointer vào runtime ngay

Ưu điểm: có thể bắt đầu durable resume và `AgentRun` integration sớm. Nhược điểm: quyết định framework trước measurement, thêm package/checkpoint schema/persistence boundary của V4-003 và trùng coordination với PostgreSQL orchestration hiện hữu.

Rejected. Persistent checkpointer chỉ được cân nhắc bằng ADR/task mới khi current requirement thực sự cần pause/resume qua process restart.

## Spike architecture

Spike có hai runner tạm thời cùng nhận một project-authored synthetic scenario và không import source/DB/provider:

```text
Synthetic typed state
  ├─ direct runner: propose → validate → apply/fallback
  └─ LangGraph runner: StateGraph nodes/edges → validate → apply/fallback
                              └─ InMemorySaver for bounded recovery case
```

Scenario đại diện dùng validator responsibility vì nó có conditional branch và retry cap rõ từ V4-001. Planner/analyst không cần graph riêng trong spike; tool/policy/application contract giống nhau và không có evidence rằng ba responsibility phải nối thành một graph.

State chỉ chứa:

- `schema_version` literal;
- opaque input/evidence refs synthetic;
- attempt/step counter có hard bound;
- injected outcome enum (`valid`, `transient_failure`, `invalid_output`);
- typed decision/result hoặc safe failure code.

State không chứa raw JD/CV, prompt, token, URL, secret, ORM object, database session hoặc callable/tool handle.

## Workload và measurement

### Functional scenarios

1. Happy path: proposal hợp lệ đi qua deterministic application đúng một lần.
2. Invalid output: validation fail closed thành `needs_review`, không có action mutation.
3. Transient failure: retry đúng cap rồi fallback; không loop vô hạn.
4. Recovery: node đầu hoàn tất, node sau fail một lần; LangGraph resume từ checkpoint trong cùng process và không tính node hoàn tất như một model/tool call mới.
5. Prompt/tool injection token trong synthetic data field: không thay edge, tool allow-list hoặc action.

`InMemorySaver` recovery chỉ chứng minh in-process checkpoint semantics. Không gọi nó là durable cross-process evidence; official docs yêu cầu persistent checkpointer cho boundary đó.

### Aggregate measurements

- exact Python/LangGraph version và isolated `pip freeze`;
- số distribution mới và installed size của isolated environment;
- cold import time;
- graph build/compile time;
- warm invoke p50/p95 trên bounded local iterations;
- direct invoke p50/p95 trên cùng workload;
- node execution count trước/sau injected failure;
- test pass/fail và safe outcome counts.

Không đặt latency SLO giả. Timing chỉ là local baseline; capability/complexity gate quan trọng hơn micro-benchmark.

## Decision gate

### Chấp nhận LangGraph

Chỉ chọn khi tất cả điều sau đúng:

- package cài/chạy với Python 3.13, isolated `pip check` sạch;
- typed state, bounded branch và recovery scenario pass mà không bypass V4-001 policy/application;
- current approved V4 workflow thực sự cần checkpoint/resume/replay hoặc human interrupt qua nhiều step;
- giá trị đó không thể đạt gọn hơn bằng direct workflow + `AgentRun` audit/fallback;
- dependency/runtime/persistence consequence được ghi ADR và task sau sở hữu chúng.

Nếu Accepted, V4-003 mới sửa `.in`, regenerate hash locks và clean-install; spike không sửa lock trước decision.

### Defer LangGraph, chọn direct workflow

Chọn khi framework chạy được nhưng current workflow vẫn là một bounded model proposal + deterministic validation/application, hoặc giá trị duy nhất là in-process recovery không cần thiết. ADR sẽ chấp nhận direct V4 workflow, giữ LangGraph là candidate có trigger xem lại rõ ràng và đổi thuật ngữ task sau từ `graph state` thành `run state`.

Đây là expected outcome theo requirement hiện tại, nhưng spike/ADR phải dựa trên observed evidence chứ không ghi kết luận trước khi chạy.

### Block

Nếu exact version không cài/chạy được trên Python 3.13 hoặc API chính thức không khớp spike, V4-002 ghi `Blocked` với error/version và không thêm dependency/fallback version tùy tiện. Version khác chỉ được thử khi release/migration docs chính thức giải thích compatibility.

## Security và privacy

- Chỉ dùng synthetic state; không đọc `.env.local` hoặc API key.
- Không model/provider call, live source, database, LangSmith tracing, Agent Server hoặc external telemetry config.
- Network chỉ dùng để lấy package từ configured Python package index trong isolated install.
- Console/evidence chỉ ghi version, count, timing, safe enum và size; không ghi environment variables hoặc full filesystem inventory.
- Temporary runner không được commit nếu ADR chọn direct workflow; evidence phải ghi đủ command/schema/hash/aggregate để audit decision.

## Testing và verification

- Spike runner tự test direct và graph path với exact expected state/action/node count.
- Re-run cùng synthetic input tạo cùng safe outcome; timing được báo riêng, không ảnh hưởng correctness.
- Default repository tests vẫn chạy không LangGraph và không network.
- Sau spike chạy full pytest, Ruff, mypy, pip check và Markdown link scan trên repository.
- Dependency diff phải rỗng nếu decision là direct/defer. Nếu LangGraph được Accepted, dependency change chỉ thuộc implementation plan V4-003 sau ADR.

## Deliverables

- ignored temporary spike environment/runner;
- `docs/evidence/V4-002-langgraph-direct-workflow-spike.md` với official sources, commands, version, footprint, metrics và scenario outcomes;
- ADR-012 chấp nhận LangGraph hoặc direct bounded workflow, kèm reconsideration trigger;
- update AI/architecture/roadmap/task board theo decision thực tế;
- không có runtime code/dependency nếu decision là defer/direct.

## Non-goals

- production model/provider adapter hoặc real JD/CV inference;
- persistent Postgres/SQLite checkpointer, cross-process recovery hoặc human approval UI;
- LangSmith, Agent Server, deployment SDK hoặc tracing service;
- `AgentRun` schema/migration và runtime caps của V4-003;
- planner/validator/analyst implementation của V4-004/V4-005;
- tuning/evaluation để đóng V4.

## Definition of Done

- official version/API sources và direct baseline được ghi trước spike;
- exact-version isolated install/pip check và dependency footprint có evidence;
- five functional scenarios chạy với direct/graph path tương ứng và outcome/node count rõ;
- in-memory recovery không bị gọi sai là cross-process durability;
- ADR chọn một hướng với consequence/reconsideration trigger cụ thể;
- repository lock/image không đổi trước decision;
- full repository gates và final diff pass;
- chỉ V4-002 chuyển `Done`; V4 giữ `in_progress` và task tiếp theo được mở đúng ADR.

## Tự kiểm tra spec

Spec không có placeholder, không ngầm chấp nhận LangGraph, không trộn V4-003 persistence vào spike và không dùng benchmark latency làm proxy cho product value. Functional/recovery claim có exact boundary; outcome `accept`, `defer` hoặc `block` đều có gate và hậu quả rõ. Scope đủ nhỏ cho một implementation plan documentation/spike riêng.
