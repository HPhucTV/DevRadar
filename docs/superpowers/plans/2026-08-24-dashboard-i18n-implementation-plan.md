# Dashboard I18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cung cấp toàn bộ dashboard DevRadar bằng tiếng Việt và tiếng Anh, mặc định tiếng Việt, giữ nguyên URL, query và API/domain values.

**Architecture:** Một module i18n nội bộ parse cookie `devradar_locale`, giữ hai dictionary typed có key parity và cung cấp server/client access. Root layout đọc cookie bằng Next.js 16 async `cookies()`, truyền locale/dictionary qua provider; client switch ghi cookie và `router.refresh()`. Server pages dùng dictionary trực tiếp, client panels dùng hook.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript 5.9, Node test runner; không thêm dependency.

---

### Task 1: Tạo locale parser và dictionary typed

**Files:**
- Create: `web/src/i18n/locale.ts`
- Create: `web/src/i18n/dictionaries.ts`
- Create: `web/tests/i18n.test.mjs`

- [ ] **Step 1: Viết test fail cho allow-list, default và dictionary parity**

```javascript
test("locale boundary is allow-listed and dictionaries keep parity", async () => {
  const locale = await source("src/i18n/locale.ts");
  const dictionaries = await source("src/i18n/dictionaries.ts");
  assert.match(locale, /devradar_locale/);
  assert.match(locale, /value === "en" \? "en" : "vi"/);
  assert.match(dictionaries, /satisfies Dictionary/);
  assert.match(dictionaries, /export const dictionaries/);
  assert.doesNotMatch(dictionaries, /translation missing/i);
});
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `npm test --prefix web`

Expected: FAIL vì thư mục `src/i18n` chưa tồn tại.

- [ ] **Step 3: Viết locale API nhỏ nhất**

```typescript
export const LOCALE_COOKIE = "devradar_locale";
export type Locale = "vi" | "en";

export function parseLocale(value: string | null | undefined): Locale {
  return value === "en" ? "en" : "vi";
}

export function localeTag(locale: Locale): "vi-VN" | "en-US" {
  return locale === "vi" ? "vi-VN" : "en-US";
}
```

- [ ] **Step 4: Viết dictionary schema và đủ hai cây key**

```typescript
export const vi = {
  shell: { subtitle: "Dữ liệu thị trường IT Việt Nam", navigationLabel: "Điều hướng chính", privacy: "Quyền riêng tư & chính sách nguồn" },
  common: { unavailable: "Không khả dụng", loading: "Đang tải...", refresh: "Làm mới", delete: "Xóa", enabled: "đã bật", paused: "đã tạm dừng" },
  routes: { overview: "Tổng quan", jobs: "Việc làm", analytics: "Phân tích", crawlerHealth: "Sức khỏe crawler", cvMatch: "Khớp CV", alerts: "Cảnh báo", customSources: "Nguồn tùy chỉnh" },
  errors: { title: "Không thể tải dữ liệu", emptyTitle: "Chưa có dữ liệu", backendUnavailable: "Không thể kết nối DevRadar API." },
  locale: { label: "Ngôn ngữ", vietnamese: "Tiếng Việt", english: "English" },
  overview: { eyebrow: "Dữ liệu hiện tại", title: "Đọc hiểu thị trường dễ dàng hơn." },
  jobs: { title: "Những việc làm đáng xem kỹ.", salaryMissing: "Chưa công bố lương", locationMissing: "Chưa công bố địa điểm" },
  analytics: { title: "Tín hiệu có mẫu số rõ ràng." },
  crawler: { title: "Tin vào nguồn trước khi tin biểu đồ." },
  cv: { title: "Xem CV của bạn phù hợp ở đâu." },
  alerts: { title: "Cảnh báo có dấu vết kiểm chứng." },
  customSources: { title: "Nguồn tùy chỉnh", urlLabel: "URL nguồn HTTPS" },
  privacy: { title: "Biết rõ DevRadar lưu gì." },
  auth: { signIn: "Đăng nhập", signOut: "Đăng xuất", username: "Tên đăng nhập", password: "Mật khẩu" },
} as const;

export type Dictionary = { [K in keyof typeof vi]: { [P in keyof (typeof vi)[K]]: string } };
export const en = {
  shell: { subtitle: "Vietnam IT market evidence", navigationLabel: "Primary navigation", privacy: "Privacy & source policy" },
  common: { unavailable: "Unavailable", loading: "Loading...", refresh: "Refresh", delete: "Delete", enabled: "enabled", paused: "paused" },
  routes: { overview: "Overview", jobs: "Jobs", analytics: "Analytics", crawlerHealth: "Crawler health", cvMatch: "CV match", alerts: "Alerts", customSources: "Custom sources" },
  errors: { title: "Data unavailable", emptyTitle: "No data yet", backendUnavailable: "DevRadar API is not reachable." },
  locale: { label: "Language", vietnamese: "Tiếng Việt", english: "English" },
  overview: { eyebrow: "Current inventory", title: "Make the market legible." },
  jobs: { title: "Jobs worth a closer look.", salaryMissing: "Salary not disclosed", locationMissing: "Location not disclosed" },
  analytics: { title: "Signals with a denominator." },
  crawler: { title: "Trust the source before the chart." },
  cv: { title: "See where your resume fits." },
  alerts: { title: "Alerts with a paper trail." },
  customSources: { title: "Custom sources", urlLabel: "HTTPS source URL" },
  privacy: { title: "Know what DevRadar keeps." },
  auth: { signIn: "Sign in", signOut: "Sign out", username: "Username", password: "Password" },
} satisfies Dictionary;
export const dictionaries: Record<Locale, Dictionary> = { vi, en };
```

- [ ] **Step 5: Chạy test/typecheck và xác nhận GREEN**

Run: `npm run test --prefix web`

Run: `npm run typecheck --prefix web`

Expected: PASS; TypeScript fail build nếu English thiếu hoặc đổi key.

- [ ] **Step 6: Commit locale core**

```powershell
git add web/src/i18n web/tests/i18n.test.mjs
git commit -m "feat: add typed dashboard dictionaries"
```

### Task 2: Nối locale vào root layout, provider và language switcher

**Files:**
- Create: `web/src/i18n/server.ts`
- Create: `web/src/i18n/locale-provider.tsx`
- Create: `web/src/components/language-switcher.tsx`
- Modify: `web/src/app/layout.tsx`
- Modify: `web/src/app/(dashboard)/layout.tsx`
- Modify: `web/src/components/app-shell.tsx`
- Modify: `web/src/app/globals.css`
- Modify: `web/tests/i18n.test.mjs`

- [ ] **Step 1: Viết static contract test fail cho async cookie và accessible switch**

```javascript
test("root locale and accessible language switch share the cookie contract", async () => {
  const layout = await source("src/app/layout.tsx");
  const control = await source("src/components/language-switcher.tsx");
  assert.match(layout, /await cookies\(\)/);
  assert.match(layout, /<html lang=\{locale\}>/);
  assert.match(control, /aria-pressed/);
  assert.match(control, /SameSite=Lax/);
  assert.match(control, /router\.refresh\(\)/);
});
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `npm test --prefix web`

Expected: FAIL vì provider/switcher chưa tồn tại.

- [ ] **Step 3: Tạo server helper và client provider**

```typescript
export async function getLocale(): Promise<Locale> {
  return parseLocale((await cookies()).get(LOCALE_COOKIE)?.value);
}

const LocaleContext = createContext<{ locale: Locale; dictionary: Dictionary } | null>(null);
export function LocaleProvider({ locale, dictionary, children }: PropsWithChildren<{ locale: Locale; dictionary: Dictionary }>) {
  return <LocaleContext.Provider value={{ locale, dictionary }}>{children}</LocaleContext.Provider>;
}
export function useI18n() {
  const value = useContext(LocaleContext);
  if (!value) throw new Error("LocaleProvider is required");
  return value;
}
```

- [ ] **Step 4: Tạo `VI | EN` control giữ route/query**

```typescript
function selectLocale(next: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${next}; Path=/; Max-Age=31536000; SameSite=Lax`;
  router.refresh();
}
```

Render hai `button type="button"` với `aria-pressed={locale === option}` và accessible name từ dictionary. Không dùng `router.push`, nên pathname/search params không đổi.

- [ ] **Step 5: Nối root/shell và responsive CSS**

Root layout đọc locale, set `<html lang={locale}>`, bọc `LocaleProvider`. App shell map route label bằng route `id`, render `LanguageSwitcher` cạnh auth control. CSS cho `.language-switcher` co gọn ở 320px, có `:focus-visible` và không đặt document `min-width`.

- [ ] **Step 6: Chạy test/lint/type/build**

Run: `npm run check --prefix web`

Expected: PASS, Next.js 16 build chấp nhận async `cookies()`.

- [ ] **Step 7: Commit integration**

```powershell
git add web/src/i18n web/src/components/language-switcher.tsx web/src/components/app-shell.tsx web/src/app/layout.tsx web/src/app/'(dashboard)'/layout.tsx web/src/app/globals.css web/tests/i18n.test.mjs
git commit -m "feat: add dashboard language switcher"
```

### Task 3: Dịch shared states, login và server-rendered pages

**Files:**
- Modify: `web/src/components/api-state.tsx`
- Modify: `web/src/components/auth-controls.tsx`
- Modify: `web/src/components/login-form.tsx`
- Modify: `web/src/components/job-list.tsx`
- Modify: `web/src/components/route-placeholder.tsx`
- Modify: `web/src/app/login/page.tsx`
- Modify: `web/src/app/(dashboard)/page.tsx`
- Modify: `web/src/app/(dashboard)/jobs/page.tsx`
- Modify: `web/src/app/(dashboard)/jobs/[jobId]/page.tsx`
- Modify: `web/src/app/(dashboard)/analytics/page.tsx`
- Modify: `web/src/app/(dashboard)/crawler-health/page.tsx`
- Modify: `web/src/app/(dashboard)/cv-match/page.tsx`
- Modify: `web/src/app/(dashboard)/alerts/page.tsx`
- Modify: `web/src/app/(dashboard)/sources/page.tsx`
- Modify: `web/src/app/(dashboard)/privacy/page.tsx`
- Modify: `web/src/app/(dashboard)/loading.tsx`
- Modify: `web/src/app/(dashboard)/error.tsx`
- Modify: `web/tests/i18n.test.mjs`

- [ ] **Step 1: Viết test fail liệt kê mọi server/shared surface phải dùng i18n**

```javascript
for (const path of serverSurfaces) {
  test(`${path} reads the dashboard dictionary`, async () => {
    assert.match(await source(path), /getDictionary|useI18n/);
  });
}
```

`serverSurfaces` chứa đầy đủ các file ở mục Files; test cũng reject `toLocaleString("vi-VN")` và `toLocaleDateString("vi-VN")` hard-code ngoài i18n.

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `npm test --prefix web`

Expected: FAIL trên các surface còn hard-code English hoặc `vi-VN`.

- [ ] **Step 3: Dịch shared components**

Client component gọi `const { dictionary: t, locale } = useI18n()`. Server component gọi `const { dictionary: t, locale } = await getDictionary()`. Ngày/số dùng `new Intl.DateTimeFormat(localeTag(locale))` và `new Intl.NumberFormat(localeTag(locale))`. Raw `job.title`, `companyName`, source name, enum/code và description không đổi.

- [ ] **Step 4: Dịch toàn bộ page copy và presentation label**

Map status/role/parser/schedule sang localized label chỉ tại render. Error component vẫn hiển thị `error.code · HTTP status`; known code dùng localized message, unknown backend message giữ safe text gốc.

- [ ] **Step 5: Chạy test/lint/type/build**

Run: `npm run check --prefix web`

Expected: PASS, không còn locale hard-code và không đổi API/domain contract.

- [ ] **Step 6: Commit server/shared translations**

```powershell
git add web/src/app web/src/components/api-state.tsx web/src/components/auth-controls.tsx web/src/components/login-form.tsx web/src/components/job-list.tsx web/src/components/route-placeholder.tsx web/src/i18n web/tests/i18n.test.mjs
git commit -m "feat: translate dashboard pages"
```

### Task 4: Dịch toàn bộ interactive panels

**Files:**
- Modify: `web/src/components/ingestion-console.tsx`
- Modify: `web/src/components/cv-match-panel.tsx`
- Modify: `web/src/components/alert-rules-panel.tsx`
- Modify: `web/src/components/custom-source-panel.tsx`
- Modify: `web/src/i18n/dictionaries.ts`
- Modify: `web/tests/i18n.test.mjs`
- Modify: `web/tests/custom-sources.test.mjs`

- [ ] **Step 1: Viết test fail cho bốn interactive panel**

```javascript
for (const panel of ["ingestion-console", "cv-match-panel", "alert-rules-panel", "custom-source-panel"]) {
  test(`${panel} consumes locale context`, async () => {
    const content = await source(`src/components/${panel}.tsx`);
    assert.match(content, /useI18n\(\)/);
    assert.doesNotMatch(content, /toLocaleString\("vi-VN"\)/);
  });
}
```

- [ ] **Step 2: Chạy test và xác nhận RED**

Run: `npm test --prefix web`

Expected: FAIL vì panel chưa gọi `useI18n()`.

- [ ] **Step 3: Thay toàn bộ copy tương tác bằng dictionary**

Bao phủ validation, confirm, notice, button busy state, label, placeholder, empty state, preview evidence, history và status presentation. Giữ nguyên values `daily_at`, `interval_minutes`, `preview_ready`, `permission_required`, selector keys, API codes, candidate provenance và URL.

- [ ] **Step 4: Cập nhật custom-source regression test theo semantic contract**

Thay assertion literal `Test crawl` bằng assertion `useI18n` và vẫn giữ các boundary assertions về `permission`, `preview`, `bypass`, `captcha`, provenance và budget. Điều này cho phép cả VI/EN mà không giảm kiểm tra an toàn.

- [ ] **Step 5: Chạy web full gate**

Run: `npm run check --prefix web`

Expected: PASS; không warning/error.

- [ ] **Step 6: Commit panel translations**

```powershell
git add web/src/components web/src/i18n/dictionaries.ts web/tests/i18n.test.mjs web/tests/custom-sources.test.mjs
git commit -m "feat: translate interactive dashboard panels"
```

### Task 5: Browser acceptance và evidence

**Files:**
- Create: `docs/evidence/V6-015-dashboard-i18n-local-no-login.md`
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `TASK_BOARD.md` (local, ignored)

- [ ] **Step 1: Chạy toàn bộ automated gates**

Run: `.venv\Scripts\python -m pytest`

Run: `.venv\Scripts\python -m ruff check .`

Run: `.venv\Scripts\python -m ruff format --check .`

Run: `.venv\Scripts\python -m mypy`

Run: `.venv\Scripts\python -m pip check`

Run: `npm run check --prefix web`

Expected: toàn bộ command exit `0`; PostgreSQL-only tests được chạy lại với `DEVRADAR_TEST_DATABASE_URL` trong runtime acceptance.

- [ ] **Step 2: Tạo ignored `.env` và restart Compose**

`.env` giữ các giá trị từ `.env.example` và đặt:

```env
DEVRADAR_DEPLOYMENT_CLASS=LOCALHOST_SERVICE
DEVRADAR_AUTH_ENABLED=false
DEVRADAR_LOCAL_NO_LOGIN_ENABLED=true
DEVRADAR_CUSTOM_SOURCES_LOCAL_ENABLED=true
```

Run migration và start theo command trong `AGENTS.md`, dùng `--env-file .env`; không dùng `down --volumes`.

- [ ] **Step 3: Browser smoke trên loopback**

Xác nhận `/sources` hiện form URL, GET/create không còn `403`, login link ẩn, `/login` redirect `/`, `VI → EN → VI` giữ route/query qua reload, `<html lang>` đổi đúng và viewport 320px không overflow/console error. Preview chỉ chạy với URL mà operator có quyền và vẫn dừng an toàn trước CAPTCHA/auth/paywall/anti-bot.

- [ ] **Step 4: Ghi evidence có command output, boundary và ảnh smoke**

Evidence ghi commit SHA, test counts, Compose health, locale smoke, custom-source API result và giới hạn chưa kiểm thử. Không ghi cookie, token, raw CV, secret hoặc raw source body.

- [ ] **Step 5: Cập nhật roadmap/task board và commit**

```powershell
git add docs/evidence/V6-015-dashboard-i18n-local-no-login.md README.md docs/ROADMAP.md
git commit -m "docs: record bilingual local dashboard evidence"
```

`TASK_BOARD.md` được cập nhật local nhưng không stage vì đã bị Git ignore.
