# Thiết kế dashboard song ngữ và local no-login

## 1. Mục tiêu

DevRadar cung cấp toàn bộ giao diện dashboard bằng tiếng Việt và tiếng Anh, mặc định tiếng Việt, đồng thời cho phép single operator sử dụng deployment `LOCALHOST_SERVICE` mà không cần đăng nhập. Custom Sources được bật trong cấu hình local và vẫn giữ mọi boundary chống SSRF, access-control bypass, cross-source data leak và false market claim hiện có.

Thiết kế này áp dụng cho dashboard, trang login khi chạy protected/public, shared shell, navigation, form, validation, loading/empty/error state và thông báo tương tác. API wire contract, domain enum, URL, tên công ty, job content và dữ liệu nguồn không bị dịch hoặc đổi nghĩa.

## 2. Non-goals

- Không thêm ngôn ngữ thứ ba, dịch máy hoặc external translation service.
- Không đổi URL thành `/vi/...` hoặc `/en/...`.
- Không dịch raw job description, CV, source response, API code hoặc database value.
- Không xóa session authentication khỏi codebase, migration hoặc protected/public deployment.
- Không nới CAPTCHA, authentication, paywall, anti-bot, SSRF, redirect, host/path hoặc source-approval policy.
- Không bật Custom Sources trong deployment `PUBLIC`.

## 3. UX song ngữ

Header có segmented control `VI | EN` đặt cạnh trạng thái session. Control dùng button semantic, có `aria-pressed`, focus state và label rõ cho screen reader. Tiếng Việt là mặc định khi chưa có lựa chọn hợp lệ.

Khi đổi ngôn ngữ:

1. client ghi cookie `devradar_locale=vi|en` với `Path=/`, `SameSite=Lax` và max age một năm;
2. client refresh route hiện tại;
3. server render lại cùng URL bằng dictionary tương ứng;
4. `<html lang>` và định dạng ngày/số đổi đồng bộ.

Không reload sang route khác, không mất filter/query hiện tại và không lưu locale trong token, URL hoặc backend database.

## 4. Kiến trúc i18n

Không thêm dependency. Module i18n nội bộ có bốn trách nhiệm:

- parse locale từ cookie bằng allow-list `vi|en`, fallback `vi`;
- cung cấp hai dictionary có cùng key set;
- cung cấp server helper cho Server Component;
- cung cấp `LocaleProvider`/hook cho interactive Client Component.

Shared shell lấy locale server-side, map navigation bằng route `id` thay vì thay đổi contract `routes.json`, và truyền dictionary client cần qua provider. Mỗi Server Component lấy translator ở boundary page; các panel client dùng hook. API/domain layer không phụ thuộc i18n.

Dictionary được chia theo namespace thực tế như `shell`, `common`, `overview`, `jobs`, `analytics`, `crawler`, `cv`, `alerts`, `customSources`, `privacy`, `auth` và `errors`. TypeScript kiểm key parity; test runtime cũng so sánh hai cây key để ngăn thiếu bản dịch.

## 5. Phạm vi nội dung được dịch

- brand subtitle, navigation, footer và language control;
- page intro, heading, description và cohort caveat;
- label, placeholder, button, badge presentation và helper text;
- loading, empty, validation, confirmation, success và failure text;
- known API error code được map sang message theo locale;
- ngày/số/phần trăm do UI tạo, dùng `vi-VN` hoặc `en-US`.

Các giá trị `status`, `role`, parser mode và schedule kind giữ wire value tiếng Anh, chỉ presentation label được dịch. Unknown backend error giữ safe message gốc nếu không có mapping; UI không tự dịch nội dung có thể làm sai nghĩa hoặc che error code.

## 6. Local no-login boundary

[ADR-025](../../decisions/0025-accept-explicit-local-no-login-mode.md) bổ sung một chế độ explicit `DEVRADAR_LOCAL_NO_LOGIN_ENABLED=true` và không thay thế [ADR-015](../../decisions/0015-accept-v6-authentication-strategy.md).

Chế độ này chỉ hợp lệ khi:

- `DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE`;
- `DEVRADAR_AUTH_ENABLED=false`;
- API/web bind loopback như Compose hiện tại.

Backend dùng một PostgreSQL `local-operator` ổn định làm owner/operator subject. User được tạo idempotently khi dependency local đầu tiên cần identity; không tạo session cookie hoặc password. Owner-scoped resource tiếp tục lưu foreign key/owner hash theo subject này.

Mutation local no-login vẫn kiểm Origin nếu request có Origin, chỉ chấp nhận allow-list loopback và giữ JSON/content-type, rate-limit cùng feature gate hiện hành. `PROTECTED` hoặc `PUBLIC` phải fail startup nếu local no-login được bật. Cấu hình vừa bật session auth vừa bật local no-login cũng bị reject vì mơ hồ.

Trong local no-login mode:

- header không hiện Sign in/Sign out;
- `/login` redirect về dashboard;
- BFF không tự tạo session hoặc lưu password;
- Custom Sources, CV, matching và các owner-scoped local feature dùng singleton local operator;
- operator-only local action tiếp tục được phép theo explicit local mode.

Protected/public giữ login, HttpOnly session, CSRF, role và owner isolation hiện tại. Không xóa auth table, endpoint backend hoặc migration lịch sử.

## 7. Cấu hình local và restart

Tạo `.env` bị Git ignore từ `.env.example`, không ghi secret thật vào Git. Cấu hình tối thiểu:

```env
DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE
DEVRADAR_AUTH_ENABLED=false
DEVRADAR_LOCAL_NO_LOGIN_ENABLED=true
DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED=true
```

Compose được chạy bằng `--env-file .env`, áp Alembic migration hiện hành, rồi start database/API/web. Không dùng `.env.production.example`, không bật local no-login trên public và không xóa named volume trong teardown.

## 8. Error handling

- Cookie locale sai hoặc quá dài fallback `vi`, không trả 500.
- Dictionary thiếu key làm test/build fail thay vì hiển thị key thô.
- Public/protected + no-login hoặc auth + no-login làm startup fail với stable safe code.
- Không tạo được local operator làm request owner-scoped fail an toàn; không fallback sang anonymous/shared header.
- Known API code có localized presentation nhưng code kỹ thuật vẫn hiển thị để chẩn đoán.
- Custom Sources chưa bật vẫn trả `custom_sources_disabled`; cấu hình local sau restart phải loại lỗi này.

## 9. Verification và acceptance

### Automated

- locale parser chỉ nhận `vi|en`, mặc định `vi`;
- VI/EN dictionary có key parity;
- language control có accessible state và giữ route/query;
- server/client text đổi theo cookie, `<html lang>` đúng;
- known error, date và number presentation đổi locale;
- local no-login tạo/reuse đúng một operator và giữ owner scope;
- local no-login bị reject trên `PROTECTED`/`PUBLIC` hoặc khi auth bật;
- login UI/route không xuất hiện trong local mode nhưng protected auth contract vẫn pass;
- Custom Sources GET/create/preview chạy trong local no-login mode;
- toàn bộ Python, PostgreSQL, web lint/type/build và security regression pass.

### Runtime/browser

- Compose dùng `.env` và database/API/web healthy;
- `/sources` không còn `403 custom_sources_disabled`;
- URL form hiện, profile có thể save và preview theo boundary hiện hành;
- đổi `VI → EN → VI` cập nhật navigation/page/form/error, giữ lựa chọn sau reload;
- viewport 320px không overflow, không có console error/warning;
- login link không xuất hiện và `/login` trở về dashboard trong local mode.

## 10. Rollout và compatibility

Feature i18n không đổi REST/OpenAPI contract. Local no-login là opt-in, default false trong committed example để tránh vô tình cấp quyền. `.env` cá nhân bật mode cho máy hiện tại. README, AGENTS, API/security docs và roadmap evidence phải phân biệt rõ local convenience với authentication cho public deployment.

Nếu sau này DevRadar được expose ngoài loopback, operator phải tắt local no-login và dùng ADR-015 session auth; không có auto-migration session hoặc implicit bypass.
