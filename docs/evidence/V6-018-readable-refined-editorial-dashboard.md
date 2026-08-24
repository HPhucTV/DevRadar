# V6-018 — Readable Refined Editorial dashboard

## Kết quả

- Root cause được sửa tại shared typography/navigation/layout layer; không có route-specific font patch.
- Page heading dùng `36–56px`, line-height `1.08`, tracking `-.025em`; serif chỉ còn ở page `h1`.
- Mobile navigation dùng disclosure, hỗ trợ Escape/focus return và route hiện tại có `aria-current="page"`.
- Analytics không còn overflow tại `768px`; Custom Sources không còn min-content overflow tại `320/375px`.
- Button/input chính đạt tối thiểu `44px`; supporting text không nhỏ hơn `13px`.

## Verification

- `npm run check`: `59` tests pass; lint, typecheck và Next.js production build pass.
- Compose config, web image build, Alembic upgrade, API health và `web-smoke.ps1` pass.
- Browser matrix pass trên `/`, `/jobs`, `/analytics`, `/crawler-health`, `/cv-match`, `/alerts`, `/sources`, `/privacy` tại `320`, `375`, `768`, `1024`, `1440px` ở cả VI và EN: `80` samples, document/nav overflow `0px`, không có undersized control.
- Job detail thật pass tại `320`, `768`, `1440px`; navigation giữ active state `Việc làm`.
- Mobile menu click, Escape/focus return, route-close, locale persistence và browser console pass.
- Reduced-motion CSS contract giữ nguyên; không chạy browser media emulation trong task này.
- Runtime được trả về tiếng Việt, `V6 local`, không có login form; `/login` redirect về `/`.
- Custom Sources hiện form URL/permission, không có visible error và Save mặc định disabled trước acknowledgement.

## Regression bắt được trong runtime

Browser matrix lần đầu phát hiện `/sources` tràn `119px` tại `320px` và `64px` tại `375px`.
Nguyên nhân là base `.custom-source-layout` xuất hiện sau media query và ghi đè responsive collapse.
Test source-order được thêm trước khi di chuyển media query xuống sau base rule; matrix chạy lại có overflow `0px`.

## Boundary

- Không đổi route, API/BFF, database, auth, local no-login, CV lifecycle hoặc Custom Source workflow.
- Không thêm dependency, external font, dark mode hoặc animation library.
- Protected/public authentication và SSRF/no-bypass policy giữ nguyên.

