# V6-011 — GitHub incident alerting

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `Done` — bounded CI incident route và remote drill đã được kiểm chứng.

## Boundary

- Failed/cancelled/timed-out/action-required push CI on `main` creates an owner-assigned GitHub issue.
- Manual dispatch creates an explicit `[DRILL]` issue through the same route.
- Workflow grants only `contents: read` and `issues: write`, and never checks out code or reads artifacts.
- Issue payload contains only run URL/ID, conclusion, SHA and event; no logs, secrets or application data.

## Local verification

Contract test được tạo trước workflow và fail đúng `FileNotFoundError` (`2 failed`). Sau khi thêm workflow,
targeted pytest đạt `2 passed`; Ruff lint/format cho test file đều exit `0`. Static trust-boundary scan
không thấy checkout, artifact download hoặc `secrets.` trong workflow.

Full local gate trước push: `252 passed, 61 skipped`; Ruff lint/format, mypy và pip check đều exit `0`.

## Remote verification

- [DevRadar CI run #24](https://github.com/HPhucTV/DevRadar/actions/runs/32617555469) trên SHA `e7fa056`
  hoàn tất `success` với đủ bảy job. Success-path [alert run](https://github.com/HPhucTV/DevRadar/actions/runs/32617848169)
  kết thúc `skipped` và không tạo `[INCIDENT]` issue.
- Manual [routing drill run](https://github.com/HPhucTV/DevRadar/actions/runs/32617878907) được dispatch
  lúc `2026-08-23T04:26:27Z`, chạy từ `04:26:30Z` đến `04:26:39Z` và kết thúc `success`.
- [Drill issue #9](https://github.com/HPhucTV/DevRadar/issues/9) được `github-actions[bot]` tạo lúc
  `04:26:36Z`, assign đúng `HPhucTV`. Title, author, assignee và body được so exact allow-list; body chỉ
  có run URL/ID, `drill`, commit SHA, event và runbook warning.
- Sau assertion, issue nhận comment `Routing drill verified; no production incident.` và được đóng lúc
  `04:28:27Z` với `state_reason=completed`.

## Boundary còn mở

Route này chỉ quan sát CI. Public uptime, HTTPS ingress, managed application secrets và encrypted
off-host PostgreSQL backup vẫn là V6 closeout gates.
