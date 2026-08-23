# V6-005 — Backup/restore, monitoring và runbooks

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — local drill đã pass; lịch backup/encryption/alert provider public còn thiếu.

## Đã triển khai

- `scripts/backup.ps1` stream PostgreSQL custom archive qua Docker, không ghi secret vào log và lưu mặc
  định trong thư mục `/backups/` bị Git ignore.
- `scripts/restore.ps1` restore archive vào database tạm, kiểm tra Alembic version table và drop database
  sau drill (trừ khi operator chọn `-KeepDatabase`).
- `scripts/monitor.ps1` bounded JSON health probe có latency threshold và tùy chọn HTTPS.
- [ADR-017](../decisions/0017-accept-postgresql-backup-restore-and-bounded-monitor.md) giữ runtime lean;
  chưa thêm Prometheus/OpenTelemetry/monitoring SaaS.
- Runbooks: [backup/restore](../runbooks/backup-restore.md), [deploy/rollback](../runbooks/deploy-rollback.md)
  và [incident response](../runbooks/incident-response.md).

## Verification

```text
Compose fresh PostgreSQL + migration head: pass
backup.ps1: backup=pass, 609,543,592 bytes, custom archive
restore.ps1: restore=pass, temporary database devradar_restore_check, Alembic table verified, database dropped
monitor.ps1: JSON devradar_health_probe, status=ok, latencyMs=328.417, thresholdMs=2000
Compose teardown: container/network removed, named volume preserved
```

Fresh rerun ngày 2026-08-23 trên Compose database mới: `backup.ps1` tạo custom archive
`610,431,168` bytes, `restore.ps1` restore thành công vào database tạm
`devradar_restore_d86624348b86` và xác nhận `alembic_version`, sau đó tự drop database. `monitor.ps1`
trả JSON `status=ok`, `latencyMs=458.292`, `thresholdMs=2000`. Archive local đã được xóa sau kiểm tra.

## Boundary còn mở

- Chưa có scheduled encrypted backup trên deployment provider hoặc off-host retention evidence.
- Chưa test object-storage access policy, key rotation, restore RPO/RTO hoặc alert routing thật.
- `health` là process health; database readiness và business SLO vẫn cần smoke/run metrics riêng.
