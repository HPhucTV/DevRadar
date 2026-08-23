# V6-004 — CI/CD, deploy và rollback

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — command surface và CI contract đã có; public deploy evidence còn thiếu.

## Đã triển khai

- `.github/workflows/ci.yml` tách Python quality/default tests, PostgreSQL integration, web quality,
  Compose migration/API smoke và Trivy critical/high advisory gate.
- CI build riêng API image không browser và crawler image có Playwright; hai image được scan bằng cùng
  Trivy digest pinned, full report trước gate fixable findings.
- `.github/dependabot.yml` theo dõi pip, npm, Docker base image và GitHub Actions.
- Compose nhận image qua `DEVRADAR_APP_IMAGE`, giữ mặc định local `devradar-app:local`.
- `scripts/smoke.ps1` bounded health smoke, hỗ trợ bắt buộc HTTPS.
- `scripts/migrate.ps1` chỉ expose `check` và `upgrade`; không có downgrade tự động.
- `scripts/deploy.ps1` chạy config → build/inspect → database health → migration → API health → smoke,
  đồng thời fail-closed cho protected/public env thiếu HTTPS/auth/managed secret/CORS/operator hash/
  non-default database password.
- `scripts/rollback.ps1` chuyển application image đã tồn tại và chạy lại smoke; schema không tự downgrade.
- ADR-016 khóa decision boundary.

## Verification

```text
PowerShell help/parser: smoke, migrate, deploy và rollback đều parse được
deploy.ps1 -SkipBuild với image đã build: migration=upgrade, smoke=pass, deploy=pass
rollback.ps1 về image đã tồn tại devradar-app:v6-004-smoke: smoke=pass, rollback=pass
docker compose ... down: container/network removed, named volume preserved
```

Fresh rerun ngày 2026-08-23 sau khi V6-010 được commit: `deploy.ps1 -SkipBuild` trả
`deploy=pass image=devradar-app:local`, sau đó `rollback.ps1` về `devradar-app:v6-004-smoke` trả
`rollback=pass`; cả hai health smoke đều trả `status=ok`.

Remote CI evidence: [GitHub Actions run #14](https://github.com/HPhucTV/DevRadar/actions/runs/32614540019)
trên SHA `3bb3ec7` hoàn tất `success` ngày 2026-08-23 sau `4m59s`. Các job Python quality/default
tests, PostgreSQL integration, web tests/lint/typecheck/build, Compose migration/API smoke và Trivy
critical/high gate đều `success`. Artifact `compose-smoke-32614540019` được lưu với kích thước `2.3 KB`,
digest `sha256:93d121300c97ba15f6683fe048f217c9136dca1374905824b17973ebe7fe71ce` và retention 14 ngày
theo workflow. Run đầu tiên phát hiện `npm ci` thiếu `@emnapi/core/runtime` trên Linux; lockfile được
regenerate bằng Node 22/npm 10 và run #2 đã xác nhận clean install.

Remote rollback drill: [GitHub Actions run #17](https://github.com/HPhucTV/DevRadar/actions/runs/32615319636)
trên SHA `be67e89` hoàn tất `success` sau `5m47s`. Job đã deploy release image, chạy migration và health
smoke, rollback về `devradar-app:known-good`, rồi lưu hai artifact: `compose-smoke-32615319636`
(`2.25 KB`, digest `sha256:4c67dee7ef01ca6cd59c1f5cdca258a303ec6353cd90b7d391ac7e8b480852b4`) và
`remote-rollback-32615319636` (`2.29 KB`, digest `sha256:b207f99896f400a9e0eaf24c173062b6bee06870daabe0d615bc16802524977e`).

Latest full checkpoint: [GitHub Actions run #21](https://github.com/HPhucTV/DevRadar/actions/runs/32616323067)
trên SHA `ebc12f2` hoàn tất `success` ngày 2026-08-23. Cả bảy job Python, PostgreSQL, web, Compose,
remote rollback, remote backup/restore và Trivy đều `success`. Bốn artifact `postgresql-tests`,
`compose-smoke`, `remote-rollback` và `remote-backup` chưa expired, có retention đến 2026-09-06;
artifact backup chỉ chứa metadata/database log và không chứa dump.

## Boundary còn mở

- HTTPS public ingress, managed secret store và deploy host/public smoke vẫn cần được cấu hình ở V6-004
  closeout.
- Backup/restore và monitoring thuộc V6-005; queue pressure/Redis decision thuộc V6-006.
