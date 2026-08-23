# V6-010 — Privacy và source policy center

**Status:** `Done` ngày 2026-08-23.

## Phạm vi đã giao

Vertical slice này cung cấp một policy contract read-only và trang public `/privacy`. Contract được phục vụ
bởi `GET /api/v1/privacy`, có same-origin BFF `GET /api/devradar/privacy`, được render qua server page theo
pattern `getPrivacy()` hiện hành và có footer link từ `AppShell`. Không thêm database, dependency, authentication
mutation hoặc provider mới.

## RED/GREEN và test contract

- RED ban đầu: API contract nhận `404`; web route/BFF/page assertions fail vì resource chưa tồn tại.
- GREEN: `tests/test_privacy_api.py` kiểm tra payload exact, OpenAPI path và negative secret/raw-content scan.
- Full backend suite sau khi cập nhật OpenAPI expected-path contract: `250 passed, 61 skipped`.
- Web quality gate `npm run check --prefix web`: `12 passed`, lint pass, TypeScript pass và Next build pass.
- Build liệt kê cả `/privacy` và `/api/devradar/privacy`.

## API runtime evidence

Sau khi phát hiện `devradar-app:local` đang là image cũ (runtime trả `404`), image API được rebuild từ source
hiện tại rồi recreate. Lần gọi runtime cuối:

```text
GET http://127.0.0.1:8000/api/v1/privacy
status=200
cache-control=no-store
content-type=application/json
x-content-type-options=nosniff
referrer-policy=no-referrer
```

Payload thực tế:

```json
{
  "data": {
    "policyVersion": "privacy-v1",
    "rawCvFileRetained": false,
    "resumeProfileTtlHours": 24,
    "ownerDeletionSupported": true,
    "externalLlmCvJdAllowed": false,
    "deterministicExtractionFirst": true,
    "sourceAllowlistOnly": true,
    "permissionRequiredSourceKeys": ["geocomply-lever"]
  }
}
```

API không trả secret, raw CV/JD, webhook, database configuration hoặc URL nội bộ. `GeoComply / Lever` vẫn
hiển thị `permission required`; không có automated retrieval.

## Browser và Compose smoke

- `scripts/smoke.ps1`: `smoke=pass endpoint=http://127.0.0.1:8000/api/v1/health`.
- PostgreSQL và API Compose đều ở trạng thái `healthy`; teardown giữ nguyên named volume.
- Mở `http://127.0.0.1:3001/privacy` khi chưa đăng nhập. Browser render đúng các facts: CV file gốc không giữ
  mặc định, ResumeProfile tối đa 24 giờ, owner deletion/cascade, deterministic extraction trước LLM, không gửi
  CV/JD tới external LLM, crawler allow-list và `GeoComply / Lever: permission required`.
- Screenshot viewport: `output/playwright/v6-010-privacy-policy.png` (local-only, Git ignored).
- Khi backend không khả dụng, page dùng `ApiErrorState`; không hardcode success policy.

## Static, security và consistency gates

```text
ruff check .                         pass
ruff format --check .                pass (260 files)
mypy                                  pass (112 source files)
pip check                             pass
git diff --check                      pass
scripts/scan-secrets.ps1              secret_scan=pass
Markdown local-link scan              133 files, 477 local links, 0 invalid
TASK_BOARD.md/.env.local/output       Git ignored
```

## Boundary còn lại

Evidence này chỉ chứng minh privacy contract/page trong local Compose và browser smoke. Nó không chứng minh
HTTPS public ingress, managed secret provider, remote CI, off-host encrypted backup/RPO/RTO hoặc public alert
provider. Các blocker đó vẫn giữ nguyên ở `V6-004`, `V6-005` và `V6-007`; không đóng V6 chỉ từ slice này.
