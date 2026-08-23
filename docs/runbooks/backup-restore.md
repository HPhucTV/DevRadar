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

## Encrypted off-host repository (V6-014)

Contract đã Accepted ở [ADR-023](../decisions/0023-accept-encrypted-spaces-backup-and-uptime-boundary.md),
nhưng chỉ được gọi là production-ready sau khi operator hoàn tất các bước với Spaces thật.

### Prerequisite và secret boundary

- Tạo Spaces bucket riêng, private; giới hạn access key vào bucket backup và giữ key/password trong GitHub
  `production` environment. Không paste secret vào chat, issue, shell argument hoặc artifact.
- `DEVRADAR_RESTIC_REPOSITORY` dùng `s3:https://<region>.digitaloceanspaces.com/<bucket>`.
- `DEVRADAR_RESTIC_IMAGE` phải là GHCR digest `ghcr.io/hphuctv/devradar-restic@sha256:<64 hex>`; tag trong
  `.env.production.example` chỉ là schema placeholder, không dùng để chạy production.
- Khởi tạo repository một lần bằng chính custom restic digest, password file và Spaces key đã phê duyệt:

  ```powershell
  $env:RESTIC_PASSWORD_FILE = '<managed-password-file>'
  $env:AWS_ACCESS_KEY_ID = '<managed-at-runtime>'
  $env:AWS_SECRET_ACCESS_KEY = '<managed-at-runtime>'
  .\scripts\backup-offsite.ps1 -Action Init -Repository $env:DEVRADAR_RESTIC_REPOSITORY -ResticImage $env:DEVRADAR_RESTIC_IMAGE
  ```

  Thực hiện trên host trong maintenance window, rồi xóa env/password file theo secret procedure. Workflow
  không tự động `init` khi backup báo sai password/not found vì repository URL gõ sai có thể tạo repository
  mới ngoài ý muốn.

### Scheduled backup và retention

Dispatch `.github/workflows/backup-production.yml` sau khi production environment đủ variables/secrets. Workflow:

1. build/push custom restic artifact và resolve digest;
2. tạo PostgreSQL custom archive tạm trên host;
3. chạy encrypted restic backup tới Spaces;
4. chạy `forget --keep-daily 7 --keep-weekly 4 --prune`;
5. logout GHCR và xóa archive/password/env file trong cleanup.

Workflow artifact chỉ được chứa SHA/run ID/restic digest và pass/fail metadata, không chứa dump, password,
access key hoặc repository listing.

### Restore drill bắt buộc

1. Dùng digest/password/Spaces key hiện hành để chạy `snapshots`, `check` và chọn snapshot theo timestamp.
2. Restore vào thư mục/database cô lập. Restic giữ đường dẫn nguồn: archive được backup từ `/input/database.dump`
   sẽ xuất hiện dưới `<restore-root>/input/database.dump`.
3. Dùng `scripts/restore.ps1` restore archive đó vào PostgreSQL tạm; kiểm tra Alembic head, số row/canary không
   chứa PII trong log và API/auth/privacy smoke.
4. Ghi thời điểm snapshot, thời điểm recovery xong, data window mất tối đa (RPO), thời gian phục hồi (RTO),
   image digest và kết quả retention. Sau đó xóa archive/database tạm.

### Rotation và failure

- Rotate Spaces access key và restic password theo maintenance window; xác minh credential mới bằng `check`
  và một backup/restore trước khi revoke credential cũ. Restic password/key rotation phải theo command chính
  thức của version đã pin; không tạo repository mới thay thế mà không migration plan.
- Backup/retention/check fail phải tạo incident; không xóa local archive trước khi xác định cleanup/retry an toàn.
- DigitalOcean Uptime verification là read-only workflow riêng. Token mặc định chỉ cần `uptime:read`; check/alert
  ID thật giữ trong production variables và chỉ đóng V6-014 sau GET evidence từ provider.
