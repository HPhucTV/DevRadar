# ADR-001: Modular monolith và phase-gated stack

## Status

Accepted

## Date

2026-08-21

## Context

DevRadar là portfolio cá nhân nhưng tầm nhìn gồm crawler, API, automation, AI, agentic workflow, dashboard và production hardening. Nếu tất cả thành phần được scaffold ngay, project sẽ có nhiều runtime, dependency và failure mode trước khi có dữ liệu chứng minh chúng cần thiết.

Các capability vẫn cần boundary rõ để code không trở thành một script lớn và để có thể chạy API, crawler hoặc worker bằng entrypoint riêng khi cần.

## Decision

- Xây một repository và modular monolith với logical modules được mô tả trong [Architecture](../ARCHITECTURE.md).
- V1 chấp nhận Python, FastAPI, PostgreSQL và Docker Compose.
- API, CLI/crawler và future worker có thể là process/entrypoint khác nhau nhưng dùng cùng codebase, domain rule và database.
- Dependency/runtime chỉ được kích hoạt khi phase bắt đầu và entry gate được đáp ứng:
  - Prefect: candidate V2;
  - LLM adapter và pgvector: candidate V3;
  - LangGraph: candidate V4;
  - Next.js: candidate V5;
  - auth strategy, Redis hoặc distributed worker: candidate V6.
- ORM, crawler library, deployment provider và external AI provider không được khóa bởi ADR này; chúng cần scaffold/source/provider spike dựa trên yêu cầu thật.

## Alternatives considered

### Microservices từ đầu

Rejected vì không có team boundary, independent scaling requirement hoặc availability requirement chứng minh network/service overhead là cần thiết.

### Scaffold toàn bộ stack ngay ở V1

Rejected vì làm tăng setup, security surface và maintenance trong khi Prefect, LangGraph, frontend hoặc Redis chưa có use case chạy được.

### Một script đơn không có module boundary

Rejected vì ingestion, canonical data và API có lifecycle/trust boundary khác nhau; cách này nhanh ở demo đầu nhưng làm khó test/replay/change detection.

### Hoàn toàn technology-neutral cho tới mỗi phase

Rejected cho V1 vì project cần contract đủ cụ thể để scaffold và tích hợp. Tuy vậy, công nghệ phase sau vẫn giữ `Proposed` để tránh premature commitment.

## Consequences

### Positive

- setup V1 nhỏ và có thể chạy trên máy cá nhân;
- transaction và domain rule nằm trong một boundary, dễ giữ consistency;
- test integration ít failure mode mạng;
- vẫn có thể tách process/service sau này khi metric yêu cầu.

### Trade-offs

- module boundary phải được giữ bằng code review/test thay vì network isolation;
- deployment của API/crawler có thể chia sẻ release cadence;
- phase bắt đầu cần spike/ADR trước khi thêm candidate technology.

### Required follow-up

- V1 scaffold phải cập nhật command thật trong README/AGENTS.
- Mọi đề xuất microservice/queue mới phải chỉ ra measured bottleneck, multiple real consumers hoặc external contract mà giải pháp đơn giản hơn không đáp ứng.

