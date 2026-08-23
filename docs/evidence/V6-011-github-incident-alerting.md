# V6-011 — GitHub incident alerting

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — local contract implemented; remote routing drill pending.

## Boundary

- Failed/cancelled/timed-out/action-required push CI on `main` creates an owner-assigned GitHub issue.
- Manual dispatch creates an explicit `[DRILL]` issue through the same route.
- Workflow grants only `contents: read` and `issues: write`, and never checks out code or reads artifacts.
- Issue payload contains only run URL/ID, conclusion, SHA and event; no logs, secrets or application data.

## Local verification

Contract test được tạo trước workflow và fail đúng `FileNotFoundError` (`2 failed`). Sau khi thêm workflow,
targeted pytest đạt `2 passed`; Ruff lint/format cho test file đều exit `0`. Static trust-boundary scan
không thấy checkout, artifact download hoặc `secrets.` trong workflow.

## Boundary còn mở

Route này chỉ quan sát CI. Public uptime, HTTPS ingress, managed application secrets và encrypted
off-host PostgreSQL backup vẫn là V6 closeout gates.
