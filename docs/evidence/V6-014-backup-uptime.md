# V6-014 — Encrypted Spaces backup/restore và DigitalOcean Uptime

**Ngày ghi nhận:** 2026-08-23
**Trạng thái:** `In Progress` — repository contract và local evidence đã có; provider evidence thật còn thiếu.

## Scope đã hoàn tất trong repository

- `deploy/restic/Dockerfile` build restic `0.19.1` từ release tarball SHA-256
  `bb9b1a19040744d26d8a79be029d4e6b189c45ccc9d8831d7fe367d3c33df725`.
- Go builder dùng manifest digest `e57c41c1...`; `x/net v0.56.0`, `x/text v0.39.0` và `grpc v1.82.1`
  được override và `go mod verify` chạy trong build.
- Runtime `FROM scratch`, `USER 65532:65532`, chỉ có binary/CA bundle; image local
  `devradar-restic:v6-014` có image ID/digest `sha256:ff41c4d89c038f76a97a31f51b860bc55f611fef5fefff16d6c2b6c35050f40f`.
- `scripts/backup-offsite.ps1` khóa production vào HTTPS S3 + immutable restic digest, dùng
  `RESTIC_PASSWORD_FILE`, và chỉ cho local repository khi có explicit `-AllowLocalRepository`.
  `Backup` bắt buộc `ArchivePath`; `Restore` bắt buộc `RestorePath`; `Init` là thao tác explicit, không tự
  chạy khi backup fail.
- `.github/workflows/ci.yml` build custom restic và đưa image vào cả full HIGH/CRITICAL report lẫn fixable gate.
- `.github/workflows/backup-production.yml` build/push GHCR digest, login remote bằng stdin, chạy backup +
  retention `7 daily + 4 weekly`, chạy container theo UID/GID non-root của host và cleanup logout/temp files.
- `.github/workflows/uptime-production.yml` chỉ verify provider-side HTTPS check/alert bằng token `uptime:read`.

## Verification local

### Contract/static

```text
tests/test_v6_014_backup_uptime_contract.py: 5 passed
Docker build deploy/restic: pass
Trivy full HIGH/CRITICAL report: 0
Trivy fixable HIGH/CRITICAL gate: 0, exit 0
docker inspect: user=65532:65532, entrypoint=/usr/bin/restic
```

`actionlint v1.7.12` chạy qua `go run` trên cả ba workflow sau thay đổi cuối và pass. Đây là static workflow
evidence; nó không thay thế remote provider run.

### Local encrypted restic smoke

Path: `C:\temp\devradar-v6014-restic-smoke-6` (ngoài repository, không commit).

```text
Init: pass
Backup: pass
Check: pass
Retain (7 daily + 4 weekly): pass
Restore: pass; restored payload 21 bytes, content match
```

Restic giữ source path trong restore: archive mounted ở `/input/archive.dump` được khôi phục tại
`<restore-root>/input/archive.dump`. Smoke này dùng local repository và password test; nó không chứng minh
Spaces network, encryption key policy, retention lifecycle trên object storage hoặc host-loss durability.

## Provider gate chưa có evidence

Chưa có DigitalOcean account/billing, Spaces bucket/key, Droplet/SSH host, domain/DNS, Uptime check/alert ID
hoặc GitHub `production` environment secret. Vì vậy chưa thể kiểm chứng an toàn:

- `restic init`, encrypted backup, list/check/restore thật trên Spaces;
- retention/prune, object access policy và key/password rotation;
- measured backup/restore RPO/RTO;
- DigitalOcean Uptime `GET /v2/uptime/checks/{id}` và alert GET từ bên ngoài;
- public HTTPS/auth/privacy smoke hoặc production deploy.

V6-014, V6-005 và V6-007 vẫn `In Progress`. Không tự tạo billing, domain, credential hoặc provider resource.

## Decision/source

[ADR-023](../decisions/0023-accept-encrypted-spaces-backup-and-uptime-boundary.md) ghi rationale, threat
boundary và alternatives. Contract dựa trên [restic password/S3 documentation](https://restic.readthedocs.io/en/stable/030_preparing_a_new_repo.html),
[DigitalOcean Spaces S3 compatibility](https://docs.digitalocean.com/products/spaces/reference/s3-compatibility/)
và [DigitalOcean Uptime API](https://docs.digitalocean.com/products/uptime/reference/api/).
