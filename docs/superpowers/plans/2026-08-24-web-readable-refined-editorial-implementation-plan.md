# Web Readable Refined Editorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sửa root cause typography/overflow và nâng cấp toàn dashboard DevRadar theo hướng Refined Editorial dễ đọc, giữ nguyên VI/EN, local no-login và mọi security boundary.

**Architecture:** Giữ `AppShell` là server component, tách duy nhất `PrimaryNavigation` thành client component nhỏ để quản lý pathname và mobile disclosure. Toàn bộ visual system tiếp tục CSS-native trong `globals.css`; route components và API contracts không đổi vì các semantic class hiện có đã bao phủ dashboard.

**Tech Stack:** Next.js 16.3.2, React 19.2.8, TypeScript 5.9.3, CSS, Node test runner, Docker Compose, in-app browser verification.

---

## Scope và file map

**Create**

- `web/src/components/primary-navigation.tsx`: active-route semantics và mobile disclosure, không sở hữu data/API.
- `docs/evidence/V6-018-readable-refined-editorial-dashboard.md`: evidence chỉ được tạo sau khi mọi gate pass.

**Modify**

- `web/src/components/app-shell.tsx`: dùng `PrimaryNavigation`, giữ server-side deployment/i18n/auth responsibilities.
- `web/src/i18n/dictionaries.json`: thêm đúng một label song ngữ cho navigation disclosure.
- `web/src/app/globals.css`: type scale, control size, navigation, route grids, surface density và responsive rules.
- `web/tests/ui-redesign.test.mjs`: regression contract cho navigation, typography, touch target và overflow.
- `web/tests/i18n.test.mjs`: đưa navigation mới vào client i18n coverage.
- `TASK_BOARD.md`: thêm `V6-018` và chỉ chuyển `Done` sau evidence; file tiếp tục Git ignored.

**Deliberately unchanged**

- `web/src/contracts/routes.json`: route contract hiện có là đủ.
- API/BFF, auth, CV, Custom Sources, crawler và database code: task không thay behavior hoặc trust boundary.
- `web/package.json` và lockfile: không thêm dependency/script.

---

### Task 1: Active route và mobile navigation song ngữ

**Files:**

- Create: `web/src/components/primary-navigation.tsx`
- Modify: `web/src/components/app-shell.tsx`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/tests/ui-redesign.test.mjs`
- Modify: `web/tests/i18n.test.mjs`

- [ ] **Step 1: Viết failing navigation contract test**

Thêm test sau vào `web/tests/ui-redesign.test.mjs`:

```js
test("primary navigation exposes current route and bounded mobile disclosure", async () => {
  const navigation = await source("src/components/primary-navigation.tsx");
  const shell = await source("src/components/app-shell.tsx");

  assert.match(navigation, /usePathname\(\)/);
  assert.match(navigation, /aria-current=\{isActive \? "page" : undefined\}/);
  assert.match(navigation, /aria-expanded=\{open\}/);
  assert.match(navigation, /event\.key === "Escape"/);
  assert.match(navigation, /setOpen\(false\)/);
  assert.match(navigation, /dictionary\.shell\.navigationMenu/);
  assert.match(shell, /PrimaryNavigation/);
  assert.doesNotMatch(shell, /routes\.filter/);
});
```

Trong test `shared shell and route surfaces use redesign primitives` hiện có, thay assertion cũ:

```js
assert.match(shell, /nav-group/);
```

bằng:

```js
assert.match(shell, /PrimaryNavigation/);
```

Trong `web/tests/i18n.test.mjs`, thêm navigation vào `clientSurfaces`:

```js
const clientSurfaces = [
  "src/app/(dashboard)/error.tsx",
  "src/app/(dashboard)/loading.tsx",
  "src/components/api-state.tsx",
  "src/components/auth-controls.tsx",
  "src/components/login-form.tsx",
  "src/components/primary-navigation.tsx",
  "src/components/route-placeholder.tsx",
];
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs tests/i18n.test.mjs
```

Expected: FAIL vì `src/components/primary-navigation.tsx` chưa tồn tại. Các test cũ vẫn pass.

- [ ] **Step 3: Đọc Next.js 16 guides liên quan trước khi viết component**

Run từ repository root:

```powershell
Get-Content -Raw 'web/node_modules/next/dist/docs/01-app/01-getting-started/04-linking-and-navigating.md'
Get-Content -Raw 'web/node_modules/next/dist/docs/01-app/01-getting-started/05-server-and-client-components.md'
Get-Content -Raw 'web/node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-pathname.md'
```

Expected: xác nhận `Link`, client boundary và `usePathname()` đúng với Next.js `16.3.2`; không dùng API Pages Router hoặc training-memory pattern.

- [ ] **Step 4: Thêm label song ngữ với key parity**

Trong `web/src/i18n/dictionaries.json`, thêm key vào `shell` của cả hai locale:

```json
{
  "vi": {
    "shell": {
      "primaryNavigation": "Điều hướng chính",
      "navigationMenu": "Menu điều hướng"
    }
  },
  "en": {
    "shell": {
      "primaryNavigation": "Primary navigation",
      "navigationMenu": "Navigation menu"
    }
  }
}
```

Giữ toàn bộ key hiện có; đoạn trên chỉ mô tả hai field liền nhau trong mỗi object `shell`.

- [ ] **Step 5: Tạo client navigation component tối thiểu**

Tạo `web/src/components/primary-navigation.tsx`:

```tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState, type KeyboardEvent } from "react";
import routes from "@/contracts/routes.json";
import { useI18n } from "@/i18n/locale-provider";

export function PrimaryNavigation() {
  const pathname = usePathname();
  const { dictionary } = useI18n();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const routeLabels: Record<string, string> = {
    overview: dictionary.routes.overview,
    jobs: dictionary.routes.jobs,
    analytics: dictionary.routes.analytics,
    "crawler-health": dictionary.routes.crawlerHealth,
    "cv-match": dictionary.routes.cvMatch,
    alerts: dictionary.routes.alerts,
    "custom-sources": dictionary.routes.customSources,
  };

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      toggleRef.current?.focus();
    }
  }

  return (
    <nav
      aria-label={dictionary.shell.primaryNavigation}
      className="primary-nav"
      onKeyDown={handleKeyDown}
    >
      <button
        aria-controls="primary-navigation-links"
        aria-expanded={open}
        className="nav-toggle"
        onClick={() => setOpen((current) => !current)}
        ref={toggleRef}
        type="button"
      >
        <span aria-hidden="true" className="nav-toggle-icon">
          <span />
          <span />
          <span />
        </span>
        <span>{dictionary.shell.navigationMenu}</span>
      </button>
      <div
        className={`nav-links${open ? " is-open" : ""}`}
        id="primary-navigation-links"
      >
        {routes.filter((route) => route.showInNav).map((route) => {
          const isActive = route.path === "/"
            ? pathname === "/"
            : pathname === route.path || pathname.startsWith(`${route.path}/`);
          return (
            <Link
              aria-current={isActive ? "page" : undefined}
              href={route.path}
              key={route.id}
              onClick={() => setOpen(false)}
            >
              {routeLabels[route.id] ?? route.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
```

- [ ] **Step 6: Giữ `AppShell` là server component**

Thay `web/src/components/app-shell.tsx` bằng:

```tsx
import Link from "next/link";
import type { ReactNode } from "react";
import { AuthControls } from "@/components/auth-controls";
import { LanguageSwitcher } from "@/components/language-switcher";
import { PrimaryNavigation } from "@/components/primary-navigation";
import { getI18n } from "@/i18n/server";
import { localNoLoginEnabled } from "@/lib/deployment-mode";

export async function AppShell({ children }: { children: ReactNode }) {
  const noLogin = localNoLoginEnabled();
  const { dictionary } = await getI18n();
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand-lockup" href="/">
          <span aria-hidden="true" className="brand-mark">D</span>
          <span className="brand-copy">
            <span className="brand">DevRadar</span>
            <span className="eyebrow">{dictionary.shell.subtitle}</span>
          </span>
        </Link>
        <div className="header-actions">
          <span className="phase-badge">
            {noLogin ? dictionary.shell.phaseLocal : dictionary.shell.phaseSession}
          </span>
          <LanguageSwitcher />
          <AuthControls localNoLoginEnabled={noLogin} />
        </div>
      </header>
      <PrimaryNavigation />
      <main id="main-content">{children}</main>
      <footer className="site-footer">
        <Link href="/privacy">{dictionary.shell.privacy}</Link>
      </footer>
    </div>
  );
}
```

- [ ] **Step 7: Chạy GREEN test và typecheck**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs tests/i18n.test.mjs
npm run typecheck
```

Expected: navigation/i18n tests PASS; TypeScript exits `0`.

- [ ] **Step 8: Commit navigation slice**

```powershell
Set-Location ..
git add web/src/components/primary-navigation.tsx web/src/components/app-shell.tsx web/src/i18n/dictionaries.json web/tests/ui-redesign.test.mjs web/tests/i18n.test.mjs
git commit -m "feat: add responsive active dashboard navigation"
```

---

### Task 2: Typography, control size và shell visual system

**Files:**

- Modify: `web/src/app/globals.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Viết failing typography/navigation CSS contract**

Thêm test sau vào `web/tests/ui-redesign.test.mjs`:

```js
test("readable type scale, controls and navigation are bounded", async () => {
  const css = await source("src/app/globals.css");

  assert.match(css, /--font-ui:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif/);
  assert.match(css, /--text-xs:\.8125rem/);
  assert.match(css, /--control-min-height:44px/);
  assert.match(css, /font-size:clamp\(2\.25rem,4vw,3\.5rem\)/);
  assert.match(css, /line-height:1\.08/);
  assert.match(css, /letter-spacing:-\.025em/);
  assert.doesNotMatch(css, /15vw|font-size:clamp\(2\.65rem,7vw,5\.4rem\)/);
  assert.doesNotMatch(css, /font-size:\.(?:7\d|8)rem/);
  assert.match(css, /\.nav-links\{[^}]*flex-wrap:wrap/);
  assert.match(css, /\.nav-links a\[aria-current="page"\]/);
  assert.match(css, /\.nav-toggle\{[^}]*min-height:var\(--control-min-height\)/);
  assert.doesNotMatch(css, /\.primary-nav\{[^}]*overflow-x:auto/);
});
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs
```

Expected: FAIL tại type scale/control/navigation assertions; boundary/security tests trong file vẫn PASS.

- [ ] **Step 3: Thêm typography và interaction tokens**

Thay `:root`, `body`, global control/focus rules trong `web/src/app/globals.css` bằng các rule sau:

```css
:root{color-scheme:light;--bg:#f6f8fc;--surface:#fff;--surface-subtle:#eef2f8;--text:#132039;--muted:#69758b;--line:#dfe6f1;--accent:#4f46e5;--accent-soft:#eef2ff;--cyan:#0891b2;--success:#059669;--success-soft:#ecfdf5;--warning:#d97706;--warning-soft:#fffbeb;--danger:#b42318;--danger-soft:#fef3f2;--font-ui:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;--font-editorial:Georgia,"Times New Roman",serif;--text-xs:.8125rem;--text-sm:.875rem;--text-base:1rem;--control-min-height:44px;--radius-panel:12px;--radius-feature:16px;--radius-pill:999px;--shadow-soft:0 12px 28px rgb(19 32 57 / .08);--focus-ring:0 0 0 3px rgb(79 70 229 / .25)}
*{box-sizing:border-box}
html{background:var(--bg)}
body{min-height:100dvh;margin:0;background:radial-gradient(circle at 10% -10%,rgb(224 231 255 / .42),transparent 34rem),var(--bg);color:var(--text);font-family:var(--font-ui);font-size:var(--text-base);line-height:1.6}
a{color:inherit;text-underline-offset:.25rem}
a:hover{color:var(--accent)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:0;box-shadow:var(--focus-ring)}
button,input,select{font:inherit}
button{min-height:var(--control-min-height);border:0;cursor:pointer}
input:not([type="checkbox"]):not([type="radio"]),select{min-height:var(--control-min-height)}
button:disabled{cursor:wait;opacity:.58}
```

- [ ] **Step 4: Giảm page-heading scale và supporting text**

Dùng các rule sau cho intro/type hierarchy:

```css
.eyebrow,.status-line{margin:.3rem 0 0;color:var(--accent);font-size:var(--text-xs);font-weight:820;letter-spacing:.1em;text-transform:uppercase}
.page-intro{max-width:780px;padding:clamp(2rem,5vw,4rem) 0 2rem}
.page-intro h1,.route-panel h1{max-width:18ch;margin:.55rem 0 1rem;color:var(--text);font-family:var(--font-editorial);font-size:clamp(2.25rem,4vw,3.5rem);font-weight:500;letter-spacing:-.025em;line-height:1.08;text-wrap:balance}
.page-intro>p:not(.eyebrow),.route-description{max-width:64ch;margin:0;color:var(--muted);font-size:1rem;line-height:1.65}
.metric-card span,.metric span,.metric-card small,.metric small,.section-heading>span,.section-heading>small,.job-meta,.job-card-meta,.field-help,.match-meta,.evidence-meta,.period-note,.cohort-note{font-size:var(--text-xs)}
.auth-controls>span,.custom-source-item small,.custom-mapping-grid label{font-size:var(--text-xs)}
.phase-badge,.health-pill,.badge,.source-badge,.salary-badge,.level-badge,.language-switcher button{font-size:var(--text-xs)}
.metric-card strong,.metric strong,.score-tile,.match-score{font-variant-numeric:tabular-nums}
```

Loại các declaration cũ `font-size:.72rem`, `.74rem`, `.75rem`, `.76rem`, `.78rem` và `.8rem` khỏi các selector đã gom ở trên; giữ các declaration từ `.82rem` trở lên.

- [ ] **Step 5: Thay horizontal nav bằng wrap + disclosure CSS**

Thay rule `.primary-nav`/`.primary-nav a` hiện tại bằng:

```css
.primary-nav{margin-top:1rem;padding:.35rem;border:1px solid var(--line);border-radius:var(--radius-panel);background:rgb(255 255 255 / .9);box-shadow:0 4px 14px rgb(19 32 57 / .04)}
.nav-toggle{display:none;min-height:var(--control-min-height);align-items:center;gap:.65rem;width:100%;border-radius:.65rem;padding:.6rem .75rem;background:var(--surface);color:var(--text);font-weight:750;text-align:left}
.nav-toggle-icon{display:grid;width:1.1rem;gap:.2rem}
.nav-toggle-icon span{display:block;height:2px;border-radius:var(--radius-pill);background:currentColor}
.nav-links{display:flex;align-items:center;flex-wrap:wrap;gap:.25rem}
.nav-links a{border-radius:.55rem;color:var(--muted);font-size:var(--text-sm);font-weight:620;padding:.58rem .75rem;text-decoration:none}
.nav-links a:hover,.nav-links a:focus-visible{background:var(--accent-soft);color:var(--accent)}
.nav-links a[aria-current="page"]{background:var(--accent-soft);color:var(--accent);font-weight:780;box-shadow:inset 0 -2px 0 var(--accent)}
```

Trong media query `max-width:700px`, dùng:

```css
@media(max-width:700px){
  .app-shell{width:min(100% - 1.25rem,1180px);padding-top:.8rem}
  .site-header{align-items:flex-start;flex-wrap:wrap}
  .header-actions{margin-left:auto}
  .primary-nav{margin-top:.8rem}
  .nav-toggle{display:flex}
  .nav-links{display:none;grid-template-columns:repeat(2,minmax(0,1fr));gap:.25rem;padding:.35rem .1rem .1rem}
  .nav-links.is-open{display:grid}
  .nav-links a{min-height:var(--control-min-height);display:flex;align-items:center;padding:.65rem .75rem}
  .page-intro{padding-top:2rem}
  .filter-form,.jobs-toolbar,.rule-builder,.tag-columns,.skill-columns{grid-template-columns:1fr}
  .job-row,.job-card,.source-row,.source-card,.skill-row,.trend-row,.run-card{align-items:flex-start;flex-direction:column}
  .job-meta,.job-card-meta{justify-items:start;text-align:left}
  .section-heading{align-items:flex-start;flex-direction:column}
  .section-heading>span,.section-heading>small{margin-top:-.35rem}
  .content-section{padding:1rem}
}
```

- [ ] **Step 6: Chạy GREEN test, lint và typecheck**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs tests/i18n.test.mjs
npm run lint
npm run typecheck
```

Expected: tests PASS; ESLint và TypeScript exit `0`.

- [ ] **Step 7: Commit typography/shell slice**

```powershell
Set-Location ..
git add web/src/app/globals.css web/tests/ui-redesign.test.mjs
git commit -m "fix: stabilize dashboard typography and navigation"
```

---

### Task 3: Route grid, surface density và overflow regression

**Files:**

- Modify: `web/src/app/globals.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Viết failing route-layout contract**

Thêm test sau vào `web/tests/ui-redesign.test.mjs`:

```js
test("route grids reflow before content creates document overflow", async () => {
  const css = await source("src/app/globals.css");

  assert.match(css, /@media\(max-width:960px\)/);
  assert.match(css, /\.dashboard-grid,\.detail-grid,\.analytics-grid,\.cv-layout,\.custom-source-layout\{grid-template-columns:1fr\}/);
  assert.match(css, /\.analytics-grid>\*,\.dashboard-grid>\*,\.detail-grid>\*,\.cv-layout>\*,\.custom-source-layout>\*\{min-width:0\}/);
  assert.match(css, /\.skill-row,\.trend-row\{flex-wrap:wrap\}/);
  assert.match(css, /\.description-text,\.policy-list\{max-width:75ch\}/);
  assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /\.kpi-grid,\.metric-grid,\.health-grid\{grid-template-columns:1fr\}/);
});
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs
```

Expected: FAIL vì breakpoint `960px`, shrinkable grid children và `420px` single-column rule chưa tồn tại.

- [ ] **Step 3: Làm grid children co được và giảm card noise**

Thêm/thay các rule sau trong `web/src/app/globals.css`:

```css
.content-section,.route-panel{margin:1rem 0;padding:clamp(1.15rem,3vw,2rem);border:1px solid var(--line);border-radius:var(--radius-feature);background:var(--surface)}
.policy-callout,.alert-intro,.custom-source-policy,.cv-upload-card{box-shadow:var(--shadow-soft)}
.analytics-grid>*,.dashboard-grid>*,.detail-grid>*,.cv-layout>*,.custom-source-layout>*{min-width:0}
.skill-row,.trend-row{flex-wrap:wrap}
.skill-row>span,.trend-row>span{min-width:0;overflow-wrap:anywhere}
.description-text,.policy-list{max-width:75ch}
.description-text{margin:0;white-space:pre-wrap;line-height:1.75;overflow-wrap:anywhere}
.detail-grid dd,.profile-summary dd,.custom-preview-card span,.custom-preview-card small{overflow-wrap:anywhere}
.metric-card,.metric{min-height:7.75rem}
```

Giữ `box-shadow` hiện có khỏi base `.content-section,.route-panel`; featured panel nhận shadow bằng selector riêng ở trên.

- [ ] **Step 4: Collapse dashboard/analytics/detail/CV/source layout tại `960px`**

Thay media query grid cũ bằng:

```css
@media(max-width:960px){
  .dashboard-grid,.detail-grid,.analytics-grid,.cv-layout,.custom-source-layout{grid-template-columns:1fr}
  .dashboard-grid>.content-section,.analytics-grid>.content-section,.custom-source-layout>.content-section,.custom-source-layout>div>.content-section{margin-top:0}
}
@media(max-width:860px){
  .kpi-grid,.metric-grid,.health-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media(max-width:420px){
  .kpi-grid,.metric-grid,.health-grid{grid-template-columns:1fr}
  .header-actions{width:100%;justify-content:flex-start;margin-left:0}
  .nav-links{grid-template-columns:1fr}
}
```

Xóa các duplicate collapse rule cũ cho `.dashboard-grid`, `.detail-grid`, `.cv-layout` và `.custom-source-layout` để mỗi breakpoint chỉ có một owner.

- [ ] **Step 5: Chạy GREEN test và full web unit suite**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs
npm test
```

Expected: `59` tests PASS, `0` fail.

- [ ] **Step 6: Commit responsive route slice**

```powershell
Set-Location ..
git add web/src/app/globals.css web/tests/ui-redesign.test.mjs
git commit -m "refactor: refine responsive dashboard surfaces"
```

---

### Task 4: Full verification, runtime evidence và task closeout

**Files:**

- Create: `docs/evidence/V6-018-readable-refined-editorial-dashboard.md`
- Modify: `TASK_BOARD.md` (Git ignored; do not stage)

- [ ] **Step 1: Chạy full web quality gate**

Run:

```powershell
Set-Location web
npm run check
```

Expected: `59` tests PASS; ESLint, TypeScript và Next.js production build đều exit `0`.

- [ ] **Step 2: Kiểm tra Compose contract và rebuild web artifact**

Run từ repository root:

```powershell
Set-Location ..
docker compose --env-file .env.example --profile crawler config --quiet
docker compose --env-file .env.example build web
docker compose --env-file .env.example up database --wait
docker compose --env-file .env.example run --rm api python -m alembic upgrade head
docker compose --env-file .env.example up api web --wait
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
```

Expected: Compose config/build/start PASS; health trả trạng thái healthy; web smoke PASS. Không chạy `down --volumes`.

- [ ] **Step 3: Browser matrix cho mọi route và locale**

Kiểm tra `/`, `/jobs`, `/analytics`, `/crawler-health`, `/cv-match`, `/alerts`, `/sources`, `/privacy` ở
`320`, `375`, `768`, `1024`, `1440px`. Sau mỗi navigation/reload, đo bằng read-only browser evaluation:

```js
() => {
  const h1 = document.querySelector("main h1");
  const style = h1 ? getComputedStyle(h1) : null;
  const controls = [...document.querySelectorAll(
    "button,input:not([type=checkbox]):not([type=radio]),select",
  )].filter((element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 && rect.height < 44;
  });
  return {
    pathname: location.pathname,
    viewport: document.documentElement.clientWidth,
    documentOverflow:
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    heading: h1 && style ? {
      size: Number.parseFloat(style.fontSize),
      lineHeight: Number.parseFloat(style.lineHeight),
      letterSpacing: Number.parseFloat(style.letterSpacing),
    } : null,
    undersizedControls: controls.map((element) => ({
      tag: element.tagName,
      id: element.id,
      height: element.getBoundingClientRect().height,
    })),
    currentRouteCount: document.querySelectorAll('[aria-current="page"]').length,
    navOverflow: (() => {
      const nav = document.querySelector(".primary-nav");
      return nav ? nav.scrollWidth - nav.clientWidth : null;
    })(),
  };
}
```

Expected trên mọi sample:

- `documentOverflow === 0` và `navOverflow === 0`;
- heading `size <= 56`, `lineHeight / size >= 1.08`, tracking không chặt hơn `-0.025em`;
- `undersizedControls` rỗng;
- `currentRouteCount === 1` cho bảy route có `showInNav`; `/privacy` có `0` vì manifest chủ ý không đưa route này vào primary navigation;
- mobile menu mở/đóng bằng click, Escape trả focus về toggle;
- VI/EN switch giữ route hiện tại và copy dài không bị clip.

- [ ] **Step 4: Kiểm tra boundary không regression**

Trong browser/runtime:

1. Xác minh local header không hiển thị login/logout và `/login` redirect về `/`.
2. Mở Custom Sources: URL input, permission acknowledgement, preview-before-enable và blocked copy còn nguyên.
3. Mở CV Match: privacy/TTL/delete copy còn nguyên; không upload dữ liệu thật cho visual smoke.
4. Kiểm tra keyboard traversal qua header, mobile menu, filter, form và footer; focus ring luôn thấy được.
5. Đọc browser console; expected không có error từ React, hydration, CSS hoặc API contract mới.

- [ ] **Step 5: Ghi evidence bằng kết quả đã kiểm chứng**

Sau khi Step 1–4 pass, tạo `docs/evidence/V6-018-readable-refined-editorial-dashboard.md` với nội dung:

```markdown
# V6-018 — Readable Refined Editorial dashboard

## Kết quả

- Root cause được sửa tại shared typography/navigation/layout layer; không có route-specific font patch.
- Page heading tối đa `56px`, line-height tối thiểu `1.08`, tracking tối đa `-.025em`.
- Mobile navigation dùng disclosure, route hiện tại có `aria-current="page"`, không còn horizontal nav scroll.
- Analytics không còn overflow tại `768px`; toàn bộ route matrix có document overflow `0px`.
- Button/input chính đạt tối thiểu `44px`.

## Verification

- `npm run check`: `59` tests pass; lint, typecheck và production build pass.
- Compose config, web image build, Alembic upgrade, API health và `web-smoke.ps1` pass.
- Browser matrix pass trên `/`, `/jobs`, `/analytics`, `/crawler-health`, `/cv-match`, `/alerts`, `/sources`, `/privacy` tại `320`, `375`, `768`, `1024`, `1440px` ở VI/EN.
- Keyboard focus, mobile menu Escape/focus return, reduced-motion CSS và browser console pass.

## Boundary

- Không đổi route, API/BFF, database, auth, local no-login, CV lifecycle hoặc Custom Source workflow.
- Không thêm dependency, external font, dark mode hoặc animation library.
- Protected/public authentication và SSRF/no-bypass policy giữ nguyên.
```

- [ ] **Step 6: Cập nhật local task board sau evidence**

Thêm row sau vào V6 section của `TASK_BOARD.md`, sau `V6-017`:

```markdown
| `V6-018` | Readable Refined Editorial dashboard | Done | `V6-017` | [Design](docs/superpowers/specs/2026-08-24-web-readable-refined-editorial-design.md), [plan](docs/superpowers/plans/2026-08-24-web-readable-refined-editorial-implementation-plan.md), [evidence](docs/evidence/V6-018-readable-refined-editorial-dashboard.md): typography/nav/overflow/touch-target regressions, `59` web tests, build, Compose và VI/EN browser matrix pass; auth/SSRF/no-bypass boundary không đổi. |
```

Không dùng `git add -f`; `TASK_BOARD.md` phải tiếp tục ignored.

- [ ] **Step 7: Commit evidence và kiểm tra final diff**

```powershell
git add docs/evidence/V6-018-readable-refined-editorial-dashboard.md
git commit -m "docs: record readable dashboard evidence"
git diff --check HEAD~4..HEAD
git status --short --branch
```

Expected: diff chỉ chứa navigation/CSS/tests/i18n/evidence trong scope; status chỉ còn `.npm-cache/` user-owned nếu nó vẫn tồn tại.

---

## Execution guardrails

- Dùng `apply_patch` cho mọi edit thủ công; không format/bulk rewrite file ngoài scope.
- TDD từng task: test phải fail đúng lý do trước implementation và pass sau implementation.
- Không đổi `routes.json`, API, auth, Custom Source, CV hoặc backend để làm UI test pass.
- Không che overflow bằng `overflow-x:hidden`/`clip` ở `html` hoặc `body`; sửa grid/flex owner gây overflow.
- Không giảm font dưới `13px`, không làm control nhỏ hơn `44px`, không bỏ focus ring.
- Không stage `.npm-cache/`, `.superpowers/` hoặc `TASK_BOARD.md`.
- Nếu browser matrix phát hiện lỗi mới ngoài typography/navigation/layout, ghi rõ và dừng mở rộng scope trước khi sửa behavior khác.
