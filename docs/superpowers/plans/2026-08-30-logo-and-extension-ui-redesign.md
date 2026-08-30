# DevRadar Logo (Concept A) & Extension UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai bộ nhận diện Logo Cyber Pulse Radar (Concept A) cho DevRadar và đồng bộ toàn diện giao diện Extension (`local-extension/collector`) với Design System / Color Tokens của DevRadar Web.

**Architecture:** Tạo vector SVG assets chuẩn cho thương hiệu; tích hợp trực tiếp vào Web `AppShell` và Extension `popup.html`/`popup.css`; bảo toàn 100% hợp đồng kỹ thuật (15 runtime files, i18n keys, IDs, event listeners, test coverage).

**Tech Stack:** SVG, CSS Design Tokens, Next.js (TypeScript/JSX), Web Extension (Manifest V3, Vanilla HTML/CSS/JS), PowerShell packaging scripts.

---

### Task 1: Tạo Brand Vector Assets (SVG)

**Files:**
- Create: `docs/assets/brand/devradar-icon.svg`
- Create: `docs/assets/brand/devradar-logo.svg`

- [ ] **Step 1: Tạo file `docs/assets/brand/devradar-icon.svg`**

```xml
<svg width="80" height="80" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="80" height="80" rx="18" fill="#0F172A"/>
  <circle cx="40" cy="40" r="34" stroke="#1E293B" stroke-width="1.5" stroke-dasharray="2 3"/>
  <circle cx="40" cy="40" r="24" stroke="#0EA5E9" stroke-width="1.5" stroke-opacity="0.35"/>
  <circle cx="40" cy="40" r="15" stroke="#06B6D4" stroke-width="1.5" stroke-opacity="0.7"/>
  <path d="M40 40 L66 22 A 32 32 0 0 0 40 8 Z" fill="url(#radar-sweep-icon)" opacity="0.45"/>
  <line x1="40" y1="40" x2="66" y2="22" stroke="#38BDF8" stroke-width="2"/>
  <circle cx="40" cy="40" r="4" fill="#38BDF8"/>
  <path d="M32 36L28 40L32 44" stroke="#22D3EE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M48 36L52 40L48 44" stroke="#22D3EE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="56" cy="26" r="2.5" fill="#10B981"/>
  <defs>
    <radialGradient id="radar-sweep-icon" cx="40" cy="40" r="32" gradientUnits="userSpaceOnUse">
      <stop stop-color="#38BDF8" stop-opacity="0.75"/>
      <stop offset="1" stop-color="#0284C7" stop-opacity="0"/>
    </radialGradient>
  </defs>
</svg>
```

- [ ] **Step 2: Tạo file `docs/assets/brand/devradar-logo.svg`**

```xml
<svg width="320" height="80" viewBox="0 0 320 80" fill="none" xmlns="http://www.w3.org/2000/svg">
  <!-- Icon Mark -->
  <rect x="8" y="10" width="60" height="60" rx="14" fill="#0F172A"/>
  <circle cx="38" cy="40" r="25" stroke="#1E293B" stroke-width="1.2" stroke-dasharray="2 3"/>
  <circle cx="38" cy="40" r="18" stroke="#0EA5E9" stroke-width="1.2" stroke-opacity="0.4"/>
  <circle cx="38" cy="40" r="11" stroke="#06B6D4" stroke-width="1.2" stroke-opacity="0.7"/>
  <path d="M38 40 L58 26 A 24 24 0 0 0 38 16 Z" fill="url(#logo-sweep)" opacity="0.45"/>
  <line x1="38" y1="40" x2="58" y2="26" stroke="#38BDF8" stroke-width="1.5"/>
  <circle cx="38" cy="40" r="3" fill="#38BDF8"/>
  <path d="M32 37L29 40L32 43" stroke="#22D3EE" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M44 37L47 40L44 43" stroke="#22D3EE" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="50" cy="29" r="2" fill="#10B981"/>
  
  <!-- Typography Lockup -->
  <text x="80" y="44" font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="26" font-weight="800" letter-spacing="-0.02em" fill="#0F172A">Dev<tspan fill="#2563EB">Radar</tspan></text>
  <text x="80" y="59" font-family="system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif" font-size="9" font-weight="700" letter-spacing="0.12em" fill="#64748B">JOB MARKET INTELLIGENCE</text>

  <defs>
    <radialGradient id="logo-sweep" cx="38" cy="40" r="24" gradientUnits="userSpaceOnUse">
      <stop stop-color="#38BDF8" stop-opacity="0.75"/>
      <stop offset="1" stop-color="#0284C7" stop-opacity="0"/>
    </radialGradient>
  </defs>
</svg>
```

- [ ] **Step 3: Kiểm tra định dạng XML / SVG**

Run: `node -e "const fs = require('fs'); ['docs/assets/brand/devradar-icon.svg', 'docs/assets/brand/devradar-logo.svg'].forEach(f => console.log(f, fs.existsSync(f) && fs.readFileSync(f, 'utf8').includes('svg')));"`
Expected: Output cả 2 file `true`.

---

### Task 2: Cập nhật Logo trong Web AppShell (`web/`)

**Files:**
- Modify: `web/src/components/app-shell.tsx:19-25`
- Modify: `web/src/styles/dashboard.css` (hoặc style bổ trợ)

- [ ] **Step 1: Cập nhật `web/src/components/app-shell.tsx`**

Thay thế `<span aria-hidden="true" className="brand-mark">D</span>` bằng Cyber Pulse Radar SVG logo mark:

```tsx
          <Link className="brand-lockup" href="/">
            <span aria-hidden="true" className="brand-mark">
              <svg width="24" height="24" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="40" cy="40" r="34" stroke="#38BDF8" stroke-width="3" stroke-dasharray="3 4" stroke-opacity="0.8"/>
                <circle cx="40" cy="40" r="20" stroke="#06B6D4" stroke-width="3" stroke-opacity="0.9"/>
                <circle cx="40" cy="40" r="6" fill="#38BDF8"/>
                <path d="M40 40 L66 22 A 32 32 0 0 0 40 8 Z" fill="#38BDF8" opacity="0.35"/>
                <circle cx="56" cy="26" r="4" fill="#10B981"/>
                <path d="M30 36L26 40L30 44" stroke="#22D3EE" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M50 36L54 40L50 44" stroke="#22D3EE" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
            <span className="brand-copy">
              <span className="brand">DevRadar</span>
              <span className="brand-subtitle">{dictionary.shell.subtitle}</span>
            </span>
          </Link>
```

- [ ] **Step 2: Chạy kiểm tra Web Typescript & Linter**

Run: `npm --prefix web run check`
Expected: PASS (không có type error hoặc lint error).

---

### Task 3: Tái thiết kế Design Tokens & Styles cho Extension (`popup.css`)

**Files:**
- Modify: `local-extension/collector/src/popup/popup.css`

- [ ] **Step 1: Cập nhật biến màu & style trong `local-extension/collector/src/popup/popup.css`**

Chuyển đổi toàn bộ bảng màu từ Teal sang DevRadar Web Palette:
- `--color-background: #eaf0f8;`
- `--color-surface: rgb(255 255 255 / 0.88);`
- `--color-surface-muted: #f1f5f9;`
- `--color-text: #0f172a;`
- `--color-muted: #475569;`
- `--color-primary: #2563eb;`
- `--color-primary-hover: #1d4ed8;`
- `--color-border: #cbd5e1;`
- `--color-ring: #2563eb;`
- `--color-danger: #b91c1c;`
- Glassmorphism surfaces: `backdrop-filter: blur(14px);`
- Button primary: gradient blue, box-shadow `0 8px 18px rgb(37 99 235 / 0.2)`
- Seniority chips: Pill bo tròn `--radius-pill: 999px`, active Blue background.

- [ ] **Step 2: Xác minh CSS syntax**

Run: `node -e "const fs = require('fs'); const css = fs.readFileSync('local-extension/collector/src/popup/popup.css', 'utf8'); console.log('Length:', css.length, 'Has primary blue:', css.includes('#2563eb'));"`
Expected: Output `Has primary blue: true`.

---

### Task 4: Cập nhật Extension Popup HTML (`popup.html`)

**Files:**
- Modify: `local-extension/collector/src/popup/popup.html`

- [ ] **Step 1: Cập nhật Brand Mark SVG trong `local-extension/collector/src/popup/popup.html`**

Cập nhật `<div class="brand-mark">` với Cyber Pulse Radar SVG logo mark, bảo toàn toàn bộ `id`, `data-i18n`, `name`, `role`, `aria-*`.

- [ ] **Step 2: Chạy kiểm tra Extension Unit Tests & Packaging**

Run:
```powershell
npm --prefix local-extension/collector test
powershell -File local-extension/collector/scripts/package.ps1 -Version 0.2.0.2
powershell -File local-extension/collector/scripts/verify-package.ps1 -Version 0.2.0.2
```
Expected: `47/47` passing tests, package verification `verify=pass`.

---

### Task 5: Kiểm chứng toàn diện hệ thống (System-Wide Gates)

**Files:** N/A

- [ ] **Step 1: Chạy toàn bộ Contract Tests và Static Gates**

```powershell
.venv\Scripts\python -m pytest tests/test_production_deployment_contract.py
npm --prefix web run check
npm --prefix local-extension/collector test
```
Expected: All suites PASS.

- [ ] **Step 2: Dọn dẹp session Visual Companion**

```powershell
powershell -Command "Stop-Process -Id (Get-Content .superpowers/brainstorm/session-1/state/server.pid -ErrorAction SilentlyContinue) -ErrorAction SilentlyContinue"
```
