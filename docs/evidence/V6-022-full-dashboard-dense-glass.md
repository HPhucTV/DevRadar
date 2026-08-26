# V6-022 — Full dashboard Dense Glass redesign

## Scope

Đổi toàn bộ dashboard web DevRadar sang visual system `C1 Sidebar workspace + G2 Full Glass` đã được
owner duyệt, áp dụng cho:

- Overview;
- Jobs và Job detail;
- Analytics;
- Crawler health;
- Sources;
- CV Match;
- Alerts;
- Privacy.

Task chỉ thay presentation, shared client interaction và CSS design system. API/BFF, authentication,
source policy, ingestion lifecycle, CV privacy và alert ownership contract không đổi. Implementation được
kiểm trên commit `64acd4d03fb14771d2f0228a95cc351c374e38ef` trước evidence commit này.

## Implementation evidence

- Ba lớp CSS token: primitive → semantic → component.
- Sidebar desktop nhóm Data, Workflows và System; mobile dùng disclosure có `aria-expanded`, Escape close
  và focus return.
- Full Glass có opacity tier riêng cho shell, panel và dense data; CSS có opaque fallback khi
  `backdrop-filter` không được hỗ trợ.
- System font hỗ trợ tiếng Việt, mono/tabular chỉ cho metric/ID/date.
- Job card được thay bằng dense table/list; Collector source label rút gọn deterministic nhưng full source
  name vẫn có trong `title`/accessible context.
- Desktop Job Explorer có summary inspector dùng list payload hiện có, không client-fetch API mới; Escape
  trả focus về đúng job. Mobile dùng deep link trực tiếp.
- Overview dùng compact recent-job rows; không ép full five-column table vào half-width panel.
- Shared loading/error/empty/success surfaces, stable skeleton và reduced-motion behavior.
- Source Recipe vẫn giữ nguyên state machine, handlers, preview/mapping/import và no-bypass boundary.

## Automated gates

Chạy từ `web/`:

```text
npm run check
```

Terminal result:

```text
78 tests
78 pass
0 fail
ESLint exit 0
TypeScript exit 0
Next.js 16.3.2 production build exit 0
18/18 static generation steps complete
```

Build và local product smoke:

```text
docker compose --env-file .env --profile crawler build web
docker compose --env-file .env --profile crawler up -d web --wait
scripts/web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
```

Kết quả:

```text
devradar-web:local Built
database/api/web healthy
web_smoke=pass base_url=http://127.0.0.1:3000
```

Live verification dùng explicit localhost no-login cùng Source Recipe visibility để current owner-local
TopCV jobs tiếp tục xuất hiện. Database không bị reset hoặc purge.

## Browser matrix

Local-only runner:

```text
output/playwright/v6-022-dense-glass/verify_dashboard.py
```

Matrix gồm `9 routes × 2 locales × 4 widths = 72` cells:

| Dimension | Values | Result |
|---|---|---|
| Locale | `vi`, `en` | `72/72` đúng `html lang`; route copy hiện đúng locale |
| Width | `375`, `768`, `1024`, `1440px` | `0` document overflow |
| Controls | button/input/select/textarea/nav/action | `0` visible control dưới `44px` |
| 200% CSS zoom simulation | 9 routes | `0` overflow; `0` focused-control obstruction |
| Reduced motion | Jobs | ambient/skeleton/transition đều `0.01ms`; data vẫn visible |

Mobile nav measurement:

```text
toggle 44 × 44px
aria-expanded false → true → false
Escape closes menu
focus returns to .nav-toggle
```

Desktop Job inspector:

```text
aria-expanded false → true
inspector visible without document overflow
Escape closes inspector
focus returns to .desktop-job-trigger
```

Local-only screenshot inventory: `37` PNG gồm VI/EN ở `375` và `1440px` cho cả chín route, cộng một
desktop Job inspector state. Screenshot và matrix JSON nằm trong Git-ignored `output/`, không phải tracked
release artifact.

## Contrast checks

WCAG relative-luminance calculation cho semantic pairs:

| Foreground | Background | Ratio |
|---|---|---:|
| `#0F172A` ink | `#FFFFFF` | `17.85:1` |
| `#475569` muted | `#FFFFFF` | `7.58:1` |
| white | `#2563EB` primary | `5.17:1` |
| `#047857` success | white | `5.48:1` |
| `#B45309` warning | `#FFFBEB` | `4.84:1` |
| `#B91C1C` danger | `#FEF2F2` | `5.91:1` |
| `#CBD5E1` sidebar text | `#0F172A` | `12.02:1` |

## Browser-found regressions and TDD fixes

### Source shortcut target size

- RED: UI contract yêu cầu `.recipe-shortcuts button` dùng `--control-min-height`; browser đo `38px` cho
  cả 10 shortcuts.
- GREEN: selector override dùng `44px`; browser rerun đo `10/10` shortcuts bằng `44px`.

### Overview recent jobs clipping

- RED: Overview contract yêu cầu `<JobList compact>`; screenshot cho thấy five-column table bị clip trong
  half-width activity panel dù document không overflow.
- GREEN: compact variant dùng one-column direct-link rows và không mở inspector; computed grid là
  `minmax(0px, 1fr)` và screenshot không còn clipped columns.

## Privacy and security regression evidence

Existing tests tiếp tục chứng minh:

- Crawler health không POST hoặc poll mutation.
- Source Recipe BFF từ chối arbitrary fetch/code fields; UI không thêm credential/proxy/bypass input.
- CV client không dùng browser owner token/localStorage và giữ bounded file/delete contract.
- Alert UI không lộ webhook URL và vẫn dùng session/CSRF boundary.
- Privacy route vẫn render truth fields về CV retention, external model và source access controls.
- Local no-login vẫn explicit; session auth route vẫn tồn tại cho protected deployment.

## Remaining boundary

- Opaque fallback được khóa bằng CSS source contract; current Chromium hỗ trợ blur nên fallback branch
  không thể được live-rendered trong cùng engine.
- 200% gate dùng CSS zoom simulation trong headless Chromium để kiểm reflow/focus obstruction; native
  browser zoom shortcut chưa được tự động hóa.
- Task không thêm dark mode, Telegram integration, chart/animation dependency hoặc public deployment claim.
