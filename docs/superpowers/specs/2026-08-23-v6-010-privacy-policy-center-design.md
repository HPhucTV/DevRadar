# V6-010 — Privacy & source policy center

## Goal

Cung cấp một privacy notice có thể truy cập công khai, dùng cùng contract API và UI, để operator/candidate
biết chính xác DevRadar giữ gì, xóa thế nào, AI boundary ra sao và source nào chưa được phép tự động truy xuất.

## Contract

`GET /api/v1/privacy` trả `data` read-only, không yêu cầu authentication:

- `policyVersion`: version của policy contract;
- `rawCvFileRetained`: luôn `false` theo mặc định hiện hành;
- `resumeProfileTtlHours`: `24`;
- `ownerDeletionSupported`: `true`;
- `externalLlmCvJdAllowed`: `false`;
- `deterministicExtractionFirst`: `true`;
- `sourceAllowlistOnly`: `true`;
- `permissionRequiredSourceKeys`: gồm `geocomply-lever`.

Không trả password hash, secret, raw CV/JD, source URL nội bộ, webhook hoặc database configuration.

## UI/data flow

Trang server-render `/privacy` dùng helper typed `getPrivacy()` để gọi trực tiếp API backend theo pattern
các dashboard page hiện hành; BFF same-origin `/api/devradar/privacy` vẫn forward cùng contract cho browser
consumer và route contract. Nếu API unavailable, trang hiển thị lỗi an toàn thay vì bịa policy runtime.
Footer link public không phụ thuộc session.

## Verification

- API contract test kiểm tra payload exact, OpenAPI và negative secret/raw-content scan.
- Web route/BFF contract test kiểm tra route không yêu cầu token và nội dung hiển thị retention/source/AI boundary.
- Compose API smoke và browser smoke mở `/privacy`, kiểm tra các policy facts thật từ API.
