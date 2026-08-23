# Runbook: Backup và restore PostgreSQL

## Mục đích

Khôi phục dữ liệu mà không đưa archive chứa owner data vào Git/log hoặc ghi đè production ngoài maintenance
window đã được phê duyệt.

## Backup local/protected

1. Xác nhận database service healthy và `DEVRADAR_DATABASE_URL`/Compose project đúng target.
2. Chạy:

   ```powershell
   .\scripts\backup.ps1 -EnvironmentFile .env.local -ProjectName devradar -OutputPath backups\devradar-<timestamp>.dump
   ```

3. Kiểm tra output chỉ gồm byte count/path; chuyển archive vào encrypted off-host storage theo policy.
4. Không gửi archive qua chat, issue, Git hoặc log collector.

## Restore drill

```powershell
.\scripts\restore.ps1 -EnvironmentFile .env.local -ProjectName devradar -BackupPath backups\devradar-<timestamp>.dump
```

Script tạo database tạm, chạy `pg_restore`, kiểm tra `alembic_version` và drop database. Giữ database tạm
chỉ khi điều tra local; sau đó drop thủ công và xóa file theo retention policy.

## Production restore

- Freeze writes/alert dispatch và ghi incident ID.
- Dùng database/credential tách biệt, encrypted archive và maintenance window.
- Restore vào isolated target trước; chạy migration check, API smoke, auth/privacy/delete checks rồi mới
  chuyển traffic.
- Ghi timestamp, archive identity, row/data validation, RPO/RTO và operator; không ghi PII/secret.
