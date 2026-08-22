# ADR-012: Chấp nhận direct bounded workflow cho V4 và hoãn LangGraph

## Status

Accepted

## Date

2026-08-22

## Context

V4 cần planner, validator và analyst tạo typed proposal từ bounded read-only input; deterministic application code vẫn sở hữu policy, retry cap, validation và mutation. V4-001 đã cài `agent-decision-v1`, default-deny tool authorization và fail-closed application gates mà không có model/graph runtime.

LangGraph `1.2.10` được spike cô lập trên Python `3.13.14`. `StateGraph` xử lý đúng happy/invalid/transient/injection scenarios; `InMemorySaver` resume một validation node fail-once mà không chạy lại proposal node. Tuy nhiên recovery này chỉ cùng process/in-memory. Durable pause/resume qua process restart cần persistent checkpointer và thread lifecycle; current V4 requirement chưa có human interrupt, replay hoặc workflow nhiều step cần durability đó.

Spike thêm 35 distribution ngoài pip và khoảng `37,622,331` byte (`35.88 MiB`) vào isolated environment. Cold import p50 là `2,211.926 ms` so với Python process `282.008 ms` và Pydantic import `544.710 ms`. Warm graph invoke p50 là `1.4123–1.5420 ms`; direct synthetic decision là `0.0003 ms`. Timing không phải SLO nhưng cho thấy framework có cost trong khi current direct workflow đã đạt cùng safe outcomes bằng explicit bounded code. Chi tiết nằm trong [V4-002 evidence](../evidence/V4-002-langgraph-direct-workflow-spike.md).

## Decision

- V4 dùng một direct bounded workflow cho mỗi responsibility `planner`, `validator` và `analyst`.
- `agent-decision-v1`, read-only tool policy và deterministic application layer từ V4-001 tiếp tục là boundary authoritative.
- V4-003 thêm typed **run state**, `AgentRun` audit và hard limits trực tiếp; `AgentRun` không phải LangGraph checkpoint store.
- Không thêm LangGraph, checkpointer package, LangSmith, Agent Server hoặc graph deployment dependency vào runtime, lock hay Docker image.
- Mỗi run có bounded model attempt/step/tool/time/token/cost caps; provider/decision failure dùng deterministic baseline hoặc `needs_review`, không cần graph resume để giữ canonical state.
- Chỉ đánh giá lại LangGraph bằng ADR mới khi có measured requirement về multi-step human pause/resume, replay/time travel, recovery qua process failure hoặc workflow topology mà explicit direct state trở nên khó kiểm chứng hơn graph runtime.

## Official-source basis

- [Graph API overview](https://docs.langchain.com/oss/python/langgraph/graph-api) mô tả state/node/edge và compile boundary của `StateGraph`.
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) mô tả checkpoint mỗi step, replay/fault tolerance và persistent checkpointer interface.
- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) yêu cầu checkpointer/thread ID và nêu node chạy lại từ đầu khi resume.
- [Testing](https://docs.langchain.com/oss/python/langgraph/test) khuyến nghị graph/checkpointer mới cho mỗi test và hỗ trợ node/partial execution tests.
- [PyPI langgraph](https://pypi.org/project/langgraph/) ghi version `1.2.10` và Python 3.13 support tại thời điểm spike.

## Alternatives considered

### Chấp nhận LangGraph core ngay trong V4-003

Rejected. Graph API hoạt động nhưng current responsibilities là các bounded proposal độc lập, không phải durable multi-step graph. Dependency/runtime cost chưa đổi lấy capability đang được yêu cầu.

### Chấp nhận LangGraph cùng Postgres checkpointer

Rejected. Điều này thêm persistence schema/thread lifecycle và recovery semantics trước `AgentRun` contract, đồng thời chưa có cross-process pause/resume requirement.

### Không chạy spike và giữ direct workflow theo suy luận

Rejected cho V4-002. Local exact-version spike là evidence cần thiết để xác minh Python compatibility, recovery semantics và dependency cost trước decision.

## Consequences

### Positive

- Giữ runtime/dependency surface nhỏ và không có graph/checkpoint persistence thứ hai.
- Policy, validation và audit ownership vẫn explicit trong modular monolith.
- Ba responsibility có thể test độc lập bằng cùng typed contract và deterministic fallback.
- V4-003 tập trung vào run safety/audit thay vì framework integration.

### Trade-offs

- DevRadar tự sở hữu explicit run state và bounded step transition.
- Chưa có built-in time travel, interrupt/resume UI hoặc checkpoint replay.
- Nếu workflow sau này thực sự cần durable graph semantics, migration sẽ cần ADR, dependency lock, checkpoint storage và compatibility tests mới.

## Required follow-up

- V4-003 cài typed run state, `AgentRun`, redacted audit và hard limits không phụ thuộc LangGraph.
- V4-004/V4-005 implement responsibility step trực tiếp và luôn đi qua V4-001 application boundary.
- V4-006 so sánh usefulness/accuracy với deterministic baseline; phần agent không tạo giá trị phải bị loại.
