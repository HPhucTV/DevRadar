# DevRadar Readable Refined Editorial Redesign

## Trạng thái

`Approved for implementation` bởi product owner qua hội thoại ngày 2026-08-24.

Tài liệu này tinh chỉnh thiết kế
[`2026-08-23-web-modern-light-editorial-redesign-design.md`](2026-08-23-web-modern-light-editorial-redesign-design.md)
ở typography, navigation, responsive layout và interaction density. Các boundary về API, auth, privacy,
Custom Sources và no-bypass trong thiết kế cũ vẫn giữ nguyên.

## Vấn đề đã kiểm chứng

CSS và font vẫn được tải; lỗi trong ảnh không phải mất stylesheet. Root cause là type scale chung quá mạnh:

- page heading dùng `clamp(2.65rem, 7vw, 5.4rem)` và tăng thành `15vw` dưới `700px`;
- heading đạt `86.4px` ở viewport `1440px` và `56.28px` ở viewport `375px`;
- `line-height: .98` cùng `letter-spacing: -.055em` làm chữ và dấu tiếng Việt bị dồn;
- tiêu đề dài chiếm từ ba đến bốn dòng trên mobile, đẩy dữ liệu chính xuống dưới fold;
- Analytics tạo document overflow khoảng `10px` tại viewport `768px`;
- primary navigation phải cuộn ngang trên viewport hẹp;
- một số button/input hiện thấp hơn target `44px`.

Audit runtime đã kiểm tra các route `/`, `/jobs`, `/analytics`, `/crawler-health`, `/cv-match`, `/alerts`,
`/sources` và `/privacy` tại `320`, `375`, `768`, `1024` và `1440px`.

## Design read

DevRadar dùng hướng **Refined Editorial** với ưu tiên `70% usability / 30% portfolio`:

- giữ light theme và một điểm nhấn serif có kiểm soát;
- giảm hero treatment để KPI, filter, trạng thái và hành động xuất hiện sớm;
- giữ top navigation quen thuộc trên desktop;
- thay horizontal navigation trên mobile bằng disclosure menu rõ trạng thái;
- mật độ vừa phải, phù hợp vận hành hằng ngày thay vì trình diễn dữ liệu tối đa.

## Mục tiêu

1. Chữ tiếng Việt/Anh dễ đọc và không bị phóng đại hoặc dồn dấu ở mọi viewport hỗ trợ.
2. Mọi route có cùng hierarchy, spacing, surface và interaction language.
3. Người dùng xác định được route hiện tại và chuyển route không cần cuộn ngang.
4. Đưa KPI, filter, source state và hành động chính lên sớm hơn trong viewport.
5. Loại document overflow, bảo đảm keyboard/touch usability và giữ đầy đủ semantic state.
6. Không thay đổi data contract hoặc trust boundary đã được chấp nhận.

## Non-goals

- Không thay route, API/BFF, schema, polling, auth, local no-login, CV lifecycle hoặc Custom Source workflow.
- Không đưa login trở lại localhost và không làm yếu auth cho protected/public deployment.
- Không thêm UI framework, font package, icon package, animation library hoặc global state library.
- Không tải font runtime từ third party và không phụ thuộc network để render typography.
- Không thêm dark theme, command palette, chart library, drag-and-drop hoặc dashboard personalization.
- Không thay copy pháp lý, permission acknowledgement, SSRF policy hoặc no-bypass behavior.

## Visual system

### Typography

- UI/body stack: `ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif`.
- Editorial stack: `Georgia, "Times New Roman", serif`, chỉ dùng cho page `h1` và không dùng cho form,
  metric, navigation, card title hoặc status.
- Page `h1`: `font-size: clamp(2.25rem, 4vw, 3.5rem)`, `line-height: 1.08`,
  `letter-spacing: -.025em`, `font-weight: 500`, tối đa khoảng `18ch`.
- Body: tối thiểu `16px`, `line-height: 1.6`; supporting text không nhỏ hơn `13px`.
- Data number dùng tabular figures để metric và time không nhảy chiều rộng.
- Heading ngắn có thể dùng `text-wrap: balance` như progressive enhancement; natural wrapping vẫn là fallback.

### Color và surface

Giữ semantic palette hiện tại: light background, white surface, indigo action/focus, cyan secondary signal,
green success, amber warning và red danger. Thay đổi tập trung vào cách dùng:

- accent chỉ nhấn active route, primary action, focus và dữ liệu quan trọng;
- text thường phải đạt contrast `4.5:1`; border/control và focus indicator đạt non-text contrast phù hợp;
- dùng một soft shadow token cho featured/actionable panel, còn list/table ưu tiên border và spacing;
- status luôn có text/icon semantics, không chỉ dựa vào màu.

### Spacing và density

- Dùng nhịp `4/8px`; section spacing theo các mức `16/24/32/48px`.
- Page intro thu gọn còn `clamp(2rem, 5vw, 4rem)` phía trên và không tạo hero cao cố định.
- Control tương tác có min-height `44px`; icon-only control nếu có cũng có hit area tối thiểu `44x44px`.
- Container giữ `max-width: 1180px`, gutter `16px` mobile và `24px` từ tablet.

## Shared shell và navigation

`AppShell` vẫn là shell chung và không nhận data dependency mới.

- Desktop/tablet rộng: brand bên trái; trạng thái deployment, VI/EN và auth control bên phải; route list ở hàng
  navigation kế tiếp. Route list được phép wrap khi thiếu chỗ và không tạo scrollbar ngang.
- Route hiện tại có `aria-current="page"`, text weight và indicator rõ ràng.
- Dưới `700px`: route list trở thành disclosure menu có button tối thiểu `44px`, `aria-expanded`, label dịch theo
  locale và danh sách link một cột/hai cột tùy chiều rộng. Không dùng horizontal scrollbar.
- Menu đóng sau navigation; focus order theo DOM; Escape hoặc thao tác đóng rõ ràng phải hoạt động nếu implementation
  dùng custom disclosure thay native semantics.
- Local no-login tiếp tục ẩn login/logout. Protected/public session control giữ nguyên.
- Footer privacy link tiếp tục xuất hiện trên mọi dashboard route.

Nếu cần state pathname/mobile menu, dùng một client navigation component nhỏ với `next/navigation`; không thêm state
library và không chuyển toàn bộ `AppShell` thành client component.

## Route composition

### Overview `/`

- Intro gọn, KPI nằm trong viewport đầu ở desktop phổ biến.
- KPI grid dùng bốn cột desktop, hai cột tablet/mobile rộng và một cột ở viewport rất hẹp nếu nội dung cần.
- Skill demand và latest jobs dùng grid `60/40`, collapse một cột dưới `960px`.

### Jobs `/jobs` và detail

- Filter giữ nguyên field/query names, label hiển thị và action rõ ràng.
- Job card ưu tiên title, company, location; provenance, date, level và raw salary ở secondary layer.
- Detail dùng content/metadata rail trên desktop, stack một cột dưới `960px`.
- URL, source ID và description dài wrap an toàn bằng shrinkable child cùng `overflow-wrap: anywhere` khi cần.

### Analytics `/analytics`

- Cohort, denominator, coverage và analyzed count vẫn là dữ liệu cấp một.
- Grid không giữ rail `min-width` khi container thiếu chỗ; collapse dưới `960px`.
- Trend row phải co hoặc stack theo container và không tạo document overflow tại `768px`.

### Crawler Health và Custom Sources

- Tách rõ source state, action và run history.
- Custom Source form nhóm thành identity/URL, parser/schedule, mapping và budgets.
- Permission acknowledgement, access denial và `permission_required` luôn dễ thấy.
- Preview-before-enable, SSRF validation và no-bypass behavior không đổi.

### CV Match

- Trình bày thành ba bước thị giác: upload, profile, matches.
- Privacy/TTL/delete state luôn thấy được nhưng không cạnh tranh với primary action.
- Score, evidence coverage, matched/missing skills không được diễn đạt như xác suất tuyển dụng.

### Alerts

- Rule builder là featured panel và chỉ có một primary action.
- Dispatch, pause/enable và delete được phân cấp; destructive action tách màu và khoảng cách.

### Privacy

- Giới hạn text measure khoảng `65–75ch`.
- Retention, AI boundary và source policy dùng heading/callout thống nhất; wording không đổi.

## State, error handling và motion

- `ApiErrorState`, empty, loading, busy, success và disabled state dùng cùng token và spacing.
- Error giữ safe message/code hiện tại, không render raw exception, token, CV/JD text hoặc secret.
- Form error nằm cạnh field khi contract hiện có hỗ trợ; multi-error flow giữ focus recovery hợp lý.
- Motion chỉ dùng opacity/color/transform ngắn để phản hồi hover, focus, open/close và state change.
- `prefers-reduced-motion: reduce` phải tắt motion không cần thiết; correctness không phụ thuộc animation end.

## Responsive contract

- Viewport kiểm chứng bắt buộc: `320`, `375`, `768`, `1024`, `1440px`.
- Breakpoint navigation/mobile chính: `700px`.
- Breakpoint dashboard/content grid chính: `960px`.
- `documentElement.scrollWidth` phải bằng `clientWidth` trên mọi route/viewport kiểm chứng.
- Navigation không có horizontal scrollbar.
- Long URL, localized labels và numbers không ép grid rộng hơn container.
- VI và EN đều phải qua cùng viewport matrix; copy dài hơn không được bị truncate mất nghĩa.

## Component boundary dự kiến

- `web/src/app/globals.css`: token, typography, layout, responsive và state styling.
- `web/src/components/app-shell.tsx`: giữ shell/server responsibilities.
- Một navigation component nhỏ chỉ được tách nếu cần pathname/mobile disclosure state.
- Route/page/component hiện có chỉ nhận class/semantic adjustments phục vụ hierarchy đã mô tả.
- Không thêm data adapter, API wrapper hoặc component abstraction chỉ có một consumer nếu CSS/class hiện có đủ dùng.

## Testing và verification

1. Thêm regression test nhỏ nhất cho typography bounds, mobile navigation, active route semantics và CSS overflow fix.
2. Chạy `npm run test`, `npm run lint`, `npm run typecheck`, `npm run build` trong `web/`.
3. Rebuild/restart Compose web artifact trước browser verification nếu runtime không dùng hot reload.
4. Browser smoke toàn bộ route tại năm viewport, kiểm tra:
   - font family/size/line-height/letter-spacing của `h1`;
   - document và component overflow;
   - mobile menu, active route, VI/EN persistence;
   - keyboard focus order và visible focus;
   - input/button target tối thiểu `44px`;
   - loading, empty, error, disabled và long-content states có thể tái hiện an toàn.
5. Xác minh local no-login vẫn hoạt động, `/login` redirect đúng và Custom Source/CV/auth boundaries không đổi.
6. Chạy broader repository gates theo mức rủi ro và kiểm tra final diff không có dependency/API/security drift.

## Acceptance criteria

- Page heading không vượt `56px`, line-height không thấp hơn `1.08` và tracking không chặt hơn `-.025em`.
- Không route nào tạo document overflow tại viewport bắt buộc; Analytics `768px` regression được đóng.
- Mobile navigation không dùng horizontal scroll và route hiện tại có `aria-current="page"`.
- Button/input chính có hit area tối thiểu `44px`.
- Tất cả dashboard route dùng cùng Refined Editorial hierarchy ở cả VI và EN.
- Không thêm dependency, không thay API/auth/privacy/source policy và không đưa login trở lại local mode.
- Web static/build gates cùng browser matrix pass bằng evidence mới trước khi task được đánh dấu Done.
