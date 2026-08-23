# V6-012 — Production web Compose

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — local image/Compose/deploy/rollback pass; remote CI evidence pending.

## Đã triển khai

- Next.js 16.3.2 `output: "standalone"` image dùng pinned Node 22 digest, exact npm lock và non-root
  `node server.js` runtime.
- Compose web service chỉ bind loopback, gọi API qua internal DNS, có health check, read-only root,
  cache/tmp tmpfs, cap drop `ALL` và no-new-privileges.
- `web-smoke.ps1` kiểm `/login` cùng privacy BFF data path; browser CSP `connect-src` chỉ còn `'self'`.
- Deploy/rollback quản lý API + web image refs, chạy cả hai smoke và vẫn không downgrade database.
- CI contract build/smoke/rollback/scan web mà không đổi bảy required job names.
- [ADR-020](../decisions/0020-accept-nextjs-standalone-web-compose-artifact.md) khóa topology.

## Local verification

- TDD contract bắt đầu `3 failed` vì thiếu Dockerfile/service/smoke; sau implementation đạt `3 passed`.
- Fresh `npm ci`; web gate đạt 12 tests, ESLint, TypeScript và Next production build.
- Web image build từ Node manifest
  `sha256:d649c27dae7ba0137b3cef5dd75baa422c08dc3d9e3fc0c23dfb172dc3cc6436`; runtime inspect trả
  `USER node`, `CMD ["node","server.js"]`, image ID `fde0dc8a08a4` và size `103,859,535` bytes.
- Trivy đầu tiên phát hiện 9 fixable HIGH/CRITICAL findings chỉ trong npm toàn cục của Node base; app
  standalone packages có `0`. TDD removal loại npm/corepack/yarn khỏi runner; final full report còn 30
  Debian findings (`26 HIGH`, `4 CRITICAL`), tất cả `0 fixable`, và fixable gate exit `0`.
- Fresh Compose project migrate tới Alembic head, API healthy và web healthy. Host port `3000` đang được
  user-owned Node process dùng nên verification chuyển sang `127.0.0.1:33000` mà không dừng process đó.
- API smoke và web `/login` + `/api/devradar/privacy` BFF smoke đều pass. Container inspect xác nhận
  read-only root, `CapDrop=["ALL"]`, `no-new-privileges:true`, `/tmp` và `.next/cache` tmpfs.
- Dual-image deploy trả `deploy=pass api_image=devradar-app:local web_image=devradar-web:local`; rollback
  về hai tag `v6-012-known-good` trả `rollback=pass` với cả hai smoke pass; container web chạy đúng
  hardened image ID. Teardown giữ named PostgreSQL volume.
- Full local gates: `255 passed, 61 skipped`; Ruff lint/format, mypy và pip check pass. Web gate lần cuối
  đạt 12 tests, ESLint, TypeScript và terminal Next production build pass; Compose crawler profile hợp lệ.

## Boundary còn mở

- Chưa có remote CI run trên exact implementation/evidence SHA hoặc remote three-image Trivy output.
- HTTPS ingress, registry, managed secrets, off-host backup và external uptime vẫn cần provider thật.
