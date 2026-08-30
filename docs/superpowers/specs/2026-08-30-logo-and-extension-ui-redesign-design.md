# Design Specification: DevRadar Logo (Concept A) & Extension UI Redesign

**Ngày tạo:** 2026-08-30  
**Trạng thái:** Proposed (Approved by User in Brainstorming)  
**Mục tiêu:** Thiết lập bộ nhận diện thương hiệu chính thức cho DevRadar với Logo Concept A (Cyber Pulse Radar) và tái cấu trúc giao diện Extension (`local-extension/collector`) đồng bộ toàn diện với Design System / Color Tokens của DevRadar Web.

---

## 1. Bối cảnh & Mục tiêu (Context & Goals)

DevRadar là nền tảng Job Market Intelligence có provenance cho thị trường tuyển dụng IT Việt Nam. Giao diện Web hiện tại sử dụng bảng màu Slate & Electric Blue kết hợp bề mặt kính mờ (Frosted Glass / Glassmorphism). Tuy nhiên:
1. Dự án chưa có Logo và Brand mark chính thức dạng vector chất lượng cao (hiện tại Web chỉ hiển thị ký tự "D", extension hiển thị crosshair cơ bản).
2. Extension `local-extension/collector` trước đây sử dụng bảng màu xanh ngọc (Teal `#0f766e`), không đồng bộ về mặt nhận diện thương hiệu với Web (`#2563eb`, `#0f172a`, `#eaf0f8`).

### Mục tiêu cụ thể:
- **Logo Concept A (Cyber Pulse Radar):** Tạo bộ assets vector SVG hoàn chỉnh cho logo (Icon mark, Full wordmark, Favicon).
- **Web Brand Integration:** Cập nhật `AppShell` / `PrimaryNavigation` và Favicon của `web/` để hiển thị logo mới.
- **Extension UI Overhaul:** Thiết kế lại `popup.html` và `popup.css` theo bảng màu Slate, Electric Blue, Frosted Glass; giữ nguyên 100% logic JavaScript, event listeners, accessibility IDs, i18n keys và test coverage.

---

## 2. Chi tiết Thiết kế Brand & Logo (Brand Identity Specs)

### 2.1. Biểu tượng: Cyber Pulse Radar (Option A)
- **Cấu trúc hình học:**
  - Vòng quét radar đồng tâm (Concentric Radar Rings) với hiệu ứng quét góc phần tư (Radar sweep sector).
  - Cặp dấu bracket lập trình `< / >` ở trung tâm tượng trưng cho Developer / Tech.
  - Các blip tín hiệu data phát sáng (Radar blips) tượng trưng cho việc phát hiện cơ hội việc làm theo thời gian thực.
- **Bảng màu chính thức (Palette):**
  - Background Shell: Deep Slate `#0f172a` (Slate-900)
  - Primary Sweep / Radar Glow: Electric Cyan `#38bdf8` / `#06b6d4`
  - Core Tech Accent: Royal Blue `#2563eb` & Indigo `#6366f1`
  - Signal Blip (Success/Live): Neon Mint `#10b981` (Emerald-500)
  - Text Primary: Pure White `#ffffff` & Ink `#0f172a`
  - Text Secondary: Cool Slate `#94a3b8` (Slate-400) / `#64748b` (Slate-500)

### 2.2. Các biến thể Asset
1. **Icon Mark (`logo-icon.svg` / `brand-mark`):**
   - Tỷ lệ 1:1, hiển thị rõ nét từ `16x16`, `32x32`, `48x48` đến `128x128px`.
   - Ứng dụng: Favicon web, Extension toolbar icon, App shell sidebar mark.
2. **Horizontal Wordmark (`logo-wordmark.svg`):**
   - Logo icon + Chữ "**Dev**Radar" với gradient tinh tế từ `#38bdf8` sang `#818cf8` và phụ đề `JOB MARKET INTELLIGENCE`.
   - Ứng dụng: Header tài liệu, README poster, Extension header.

---

## 3. Chi tiết Tái thiết kế Extension UI (`local-extension/collector`)

### 3.1. Design Tokens & Styling (`popup.css`)
Thay thế toàn bộ các biến màu Teal cũ bằng hệ thống semantic tokens đồng bộ với `web/src/styles/tokens.css`:

```css
:root {
  color-scheme: light;
  --color-background: #eaf0f8;
  --color-canvas-ambient: radial-gradient(circle at 90% -20%, rgb(124 58 237 / 0.12), transparent 18rem),
                          radial-gradient(circle at 10% 120%, rgb(8 145 178 / 0.15), transparent 20rem),
                          #eaf0f8;
  --color-surface: rgb(255 255 255 / 0.86);
  --color-surface-card: #ffffff;
  --color-surface-muted: #f1f5f9;
  --color-border: #cbd5e1;
  --color-border-subtle: #e2e8f0;
  --color-text: #0f172a;
  --color-muted: #475569;
  --color-primary: #2563eb;
  --color-primary-hover: #1d4ed8;
  --color-primary-soft: #eff6ff;
  --color-ring: #2563eb;
  --color-success: #047857;
  --color-success-soft: #ecfdf5;
  --color-warning: #b45309;
  --color-warning-soft: #fffbeb;
  --color-danger: #b91c1c;
  --color-danger-soft: #fef2f2;
  --shadow-card: 0 4px 14px rgb(15 23 42 / 0.06);
  --shadow-panel: 0 10px 25px rgb(15 23 42 / 0.08);
  --shadow-control: 0 8px 18px rgb(37 99 235 / 0.2);
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --radius-pill: 999px;
  --font-ui: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-data: ui-monospace, "SFMono-Regular", Consolas, monospace;
}
```

### 3.2. Cấu trúc Giao diện (`popup.html`)
- **Header:**
  - Brand Mark: SVG Cyber Pulse Radar trên nền Deep Slate bo góc `--radius-md` với shadow nhẹ.
  - Title: `DevRadar Collector` với typography `1.1rem`, font-weight 750, color `#0f172a`.
  - Locale Switcher (`#locale-vi`, `#locale-en`): Tối ưu dạng segmented control kính mờ với active state Blue 600.
- **Connection Status Row:**
  - Hiển thị badge trạng thái kính mờ với status dot màu xanh ngọc `#10b981` (khi sẵn sàng) hoặc amber/red.
- **Current Recipe Card:**
  - Hiển thị thông tin recipe dạng card kính mờ `backdrop-filter: blur(12px)`.
- **Form Controls:**
  - Input URL: Font monospace, viền `#cbd5e1`, focus-ring 2 lớp rõ ràng.
  - Seniority Chip List: Dạng pill badge bo tròn, khi chọn có nền Blue 600 và chữ trắng.
  - Primary Action Button: Gradient `#2563eb` -> `#1d4ed8`, font-weight 700, icon tia sét/radar quét, shadow control.

---

## 4. Hợp đồng Kỹ thuật & Phạm vi Files (Boundaries & File Scope)

### 4.1. Files được thay đổi / thêm mới
1. `web/src/components/app-shell.tsx`: Cập nhật component brand mark sang inline SVG Cyber Pulse Radar.
2. `web/src/styles/tokens.css` / `dashboard.css`: Cung cấp class / style cho brand mark SVG trong sidebar.
3. `local-extension/collector/src/popup/popup.html`: Cập nhật inline SVG icon brand mark sang Cyber Pulse Radar và tinh chỉnh semantic class.
4. `local-extension/collector/src/popup/popup.css`: Cập nhật toàn bộ design tokens và styles sang Web-synchronized palette.
5. (Tuỳ chọn) Tạo file SVG tham chiếu độc lập `docs/assets/brand/devradar-logo.svg` và `docs/assets/brand/devradar-icon.svg`.

### 4.2. Ràng buộc bảo toàn (Non-breaking Invariants)
- **Không thay đổi danh sách 15 runtime files trong `verify-package.ps1`**: Inline SVG trong `popup.html` và file `popup.css` không làm phát sinh thêm file binary trong extension runtime package, đảm bảo `npm test`, `verify-package.ps1` và các bài test Chromium E2E tiếp tục hoạt động hoàn hảo.
- **Không đổi bất kỳ `id`, `class` cốt lõi, `name`, `data-i18n`, `role`, `aria-*` nào**: Toàn bộ script `popup.js` và `i18n.js` hoạt động nguyên vẹn 100%.

---

## 5. Kế hoạch Kiểm chứng (Verification Plan)

### 5.1. Automated Verification
1. **Extension Package & Unit Tests:**
   ```powershell
   cd local-extension/collector
   npm test
   powershell -File scripts/verify-package.ps1 -Version 0.2.0.2
   ```
2. **Web Build & Type Checks:**
   ```powershell
   cd web
   npm run check
   ```
3. **Python & Full Repository Static Checks:**
   ```powershell
   .venv\Scripts\python -m pytest tests/test_production_deployment_contract.py
   .venv\Scripts\python -m ruff check .
   ```

### 5.2. Visual Verification
- Kiểm tra trực quan Extension Popup và Web AppShell trên trình duyệt để đảm bảo độ tương phản màu, bo góc, spacing và font chữ chuẩn chỉnh theo thiết kế.
