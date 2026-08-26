# Full Dashboard Dense Glass Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current editorial card UI across all nine DevRadar web routes with the approved C1 sidebar workspace and G2 Full Glass data-dense design while preserving every API, security, privacy, and ingestion contract.

**Architecture:** Keep the existing Next.js App Router and server/client boundaries. Introduce a three-layer CSS token system, migrate the shared shell and primitives first, then move route groups onto five approved archetypes. Add client state only for mobile navigation and the job summary inspector; all filters, full job details, and mutations keep their current URL/BFF contracts.

**Tech Stack:** Next.js 16.3.2, React 19.2.8, TypeScript 5.9.3, native CSS, Node test runner, existing Python Playwright runtime for local visual evidence.

---

## File structure

### New files

- `web/src/styles/tokens.css` — primitive, semantic, and component CSS variables; motion and glass fallback.
- `web/src/styles/base.css` — reset, document background, typography, focus, buttons, forms, shared API states.
- `web/src/styles/dashboard.css` — shell, navigation, route archetypes, tables, workflows, responsive rules.
- `web/src/lib/source-display.ts` — deterministic presentation-only source label.
- `web/tests/source-display.test.mjs` — source label behavior and raw-name preservation contract.
- `docs/evidence/V6-022-full-dashboard-dense-glass.md` — verified commands, route matrix, screenshots and remaining boundaries.

### Existing files changed

- `web/src/app/globals.css` — becomes the three-file CSS entry point.
- `web/src/components/app-shell.tsx`, `primary-navigation.tsx` — C1 sidebar and workspace top bar.
- `web/src/components/api-state.tsx` and dashboard `loading.tsx`/`error.tsx` — common loading/error/empty/success language.
- `web/src/components/job-list.tsx` — data table/list and desktop summary inspector.
- Dashboard pages and operator components — archetype class structure only; no contract changes.
- `web/src/i18n/dictionaries.json` — VI/EN labels for navigation groups and job inspector.
- `web/tests/ui-redesign.test.mjs`, `i18n.test.mjs`, `routes.test.mjs`, `source-recipes.test.mjs` — design, accessibility and boundary regressions.

Do not create a UI component library, icon dependency, animation package, chart package, external font or theme framework.

## Task 1: Lock the token architecture and CSS entry point

**Files:**

- Create: `web/src/styles/tokens.css`
- Create: `web/src/styles/base.css`
- Create: `web/src/styles/dashboard.css`
- Modify: `web/src/app/globals.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Replace the old editorial token test with a failing G2 contract**

Change the first token test to load all CSS sources and assert the approved three layers:

```js
async function cssBundle() {
  return Promise.all([
    source("src/styles/tokens.css"),
    source("src/styles/base.css"),
    source("src/styles/dashboard.css"),
  ]).then((parts) => parts.join("\n"));
}

test("dense glass tokens replace the editorial theme", async () => {
  const css = await cssBundle();
  assert.match(css, /--blue-600:\s*#2563eb/i);
  assert.match(css, /--color-ink:\s*var\(--slate-900\)/);
  assert.match(css, /--glass-data:\s*rgb\(255 255 255 \/ \.88\)/);
  assert.match(css, /--motion-fast:\s*140ms/);
  assert.match(css, /--motion-component:\s*220ms/);
  assert.match(css, /--motion-route:\s*300ms/);
  assert.match(css, /@supports not \(backdrop-filter:blur\(1px\)\)/);
  assert.match(css, /@media\(prefers-reduced-motion:reduce\)/);
  assert.doesNotMatch(css, /Times New Roman|font-editorial/);
});
```

- [ ] **Step 2: Run RED**

Run:

```powershell
Set-Location web
node --test tests/ui-redesign.test.mjs
Set-Location ..
```

Expected: FAIL because `web/src/styles/*.css` do not exist and the old serif token remains.

- [ ] **Step 3: Create the three-layer tokens**

Create `tokens.css` with this exact layer shape; additional component tokens must reference semantic or primitive values rather than raw color values:

```css
:root {
  color-scheme: light;

  /* Primitive */
  --slate-50: #f8fafc;
  --slate-100: #f1f5f9;
  --slate-300: #cbd5e1;
  --slate-600: #475569;
  --slate-900: #0f172a;
  --blue-600: #2563eb;
  --violet-600: #7c3aed;
  --cyan-600: #0891b2;
  --emerald-700: #047857;
  --amber-700: #b45309;
  --red-700: #b91c1c;
  --space-1: .25rem;
  --space-2: .5rem;
  --space-3: .75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --radius-control: .5rem;
  --radius-panel: .75rem;
  --radius-surface: 1rem;
  --radius-shell: 1.25rem;

  /* Semantic */
  --color-canvas: #eaf0f8;
  --color-ink: var(--slate-900);
  --color-muted: var(--slate-600);
  --color-primary: var(--blue-600);
  --color-info: var(--cyan-600);
  --color-success: var(--emerald-700);
  --color-warning: var(--amber-700);
  --color-danger: var(--red-700);
  --glass-shell: rgb(255 255 255 / .45);
  --glass-panel: rgb(255 255 255 / .64);
  --glass-data: rgb(255 255 255 / .88);
  --glass-border: rgb(255 255 255 / .72);
  --motion-fast: 140ms;
  --motion-component: 220ms;
  --motion-route: 300ms;
  --control-min-height: 44px;

  /* Component */
  --button-bg: var(--color-primary);
  --button-fg: white;
  --input-bg: rgb(255 255 255 / .72);
  --input-border: rgb(148 163 184 / .58);
  --table-bg: var(--glass-data);
  --focus-ring-color: var(--color-primary);
}
```

- [ ] **Step 4: Replace `globals.css` with the stable import surface**

Use only imports in this order:

```css
@import "../styles/tokens.css";
@import "../styles/base.css";
@import "../styles/dashboard.css";
```

Put the current behavior-preserving reset/forms/state rules in `base.css`; put shell and route rules in `dashboard.css`. Preserve existing source-recipe selectors until their route migration task changes them.

- [ ] **Step 5: Add glass fallback and reduced-motion rules before route styling**

```css
@supports not (backdrop-filter:blur(1px)) {
  .glass-surface,
  .content-section,
  .route-panel { background: #fff; }
}

@media (prefers-reduced-motion:reduce) {
  *, *::before, *::after {
    scroll-behavior: auto !important;
    animation-duration: .01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: .01ms !important;
  }
}
```

- [ ] **Step 6: Run GREEN and commit**

Run the targeted Node test, then:

```powershell
git add web/src/app/globals.css web/src/styles web/tests/ui-redesign.test.mjs
git commit -m "style: establish dense glass design tokens"
```

Expected: the token test passes; remaining old-layout assertions may stay RED only when the next task explicitly owns them.

## Task 2: Build the C1 sidebar workspace shell

**Files:**

- Modify: `web/src/components/app-shell.tsx`
- Modify: `web/src/components/primary-navigation.tsx`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/ui-redesign.test.mjs`
- Modify: `web/tests/i18n.test.mjs`

- [ ] **Step 1: Write the failing shell/navigation contract**

Replace old top-nav expectations with:

```js
test("C1 shell groups routes in a responsive sidebar", async () => {
  const shell = await source("src/components/app-shell.tsx");
  const navigation = await source("src/components/primary-navigation.tsx");
  const css = await cssBundle();
  assert.match(shell, /skip-link/);
  assert.match(shell, /sidebar-shell/);
  assert.match(shell, /workspace-shell/);
  assert.match(shell, /workspace-header/);
  assert.match(navigation, /nav-group/);
  assert.match(navigation, /aria-current/);
  assert.match(navigation, /aria-expanded/);
  assert.match(navigation, /event\.key === "Escape"/);
  assert.match(css, /grid-template-columns:\s*190px minmax\(0,1fr\)/);
  assert.match(css, /@media\(max-width:1023px\)/);
  assert.doesNotMatch(css, /\.nav-links\{[^}]*flex-wrap:wrap/);
});
```

- [ ] **Step 2: Run RED**

Run `node --test tests/ui-redesign.test.mjs tests/i18n.test.mjs` from `web`. Expected: FAIL on missing shell classes and group labels.

- [ ] **Step 3: Restructure `AppShell` without changing auth or locale behavior**

Render this hierarchy:

```tsx
<div className="app-canvas">
  <a className="skip-link" href="#main-content">{dictionary.shell.skipToContent}</a>
  <div aria-hidden="true" className="ambient ambient-one" />
  <div aria-hidden="true" className="ambient ambient-two" />
  <div className="app-shell">
    <aside className="sidebar-shell glass-surface">
      <Link className="brand-lockup" href="/">
        <span aria-hidden="true" className="brand-mark">D</span>
        <span className="brand-copy">
          <span className="brand">DevRadar</span>
          <span className="brand-subtitle">{dictionary.shell.subtitle}</span>
        </span>
      </Link>
      <PrimaryNavigation />
      <Link className="sidebar-privacy-link" href="/privacy">{dictionary.shell.privacy}</Link>
    </aside>
    <div className="workspace-shell">
      <header className="workspace-header glass-surface">
        <span className="phase-badge">
          {noLogin ? dictionary.shell.phaseLocal : dictionary.shell.phaseSession}
        </span>
        <div className="header-actions">
          <LanguageSwitcher />
          <AuthControls localNoLoginEnabled={noLogin} />
        </div>
      </header>
      <main id="main-content">{children}</main>
    </div>
  </div>
</div>
```

Keep `localNoLoginEnabled()`, `LanguageSwitcher` and `AuthControls` calls unchanged.

- [ ] **Step 4: Group navigation by existing route IDs**

Use a fixed presentation map, not a new route source of truth:

```tsx
const groups = [
  { label: dictionary.shell.coreGroup, ids: ["overview", "jobs", "analytics", "crawler-health"] },
  { label: dictionary.shell.workflowGroup, ids: ["source-recipes", "cv-match", "alerts"] },
] as const;
```

Filter the existing `routes.json` inside each group. Preserve `aria-current`, Escape, focus return and close-on-link-click. Do not add Settings, Telegram or unavailable routes.

- [ ] **Step 5: Add VI/EN dictionary keys**

Add matching keys under both `vi.shell` and `en.shell`:

```json
{
  "skipToContent": "Bỏ qua đến nội dung chính",
  "coreGroup": "Dữ liệu",
  "workflowGroup": "Quy trình",
  "openNavigation": "Mở điều hướng",
  "closeNavigation": "Đóng điều hướng"
}
```

English values: `Skip to main content`, `Data`, `Workflows`, `Open navigation`, `Close navigation`.

- [ ] **Step 6: Implement desktop and mobile shell CSS**

Desktop uses `190px minmax(0,1fr)`. At `max-width:1023px`, sidebar becomes the fixed/top disclosure surface; the closed nav does not cover content. Open state has a scrim and the first route receives focus through the existing DOM order. Ensure all buttons/links have at least `44px` hit area.

- [ ] **Step 7: Run GREEN and commit**

Run targeted UI/i18n tests and `npm run typecheck`, then commit:

```powershell
git add web/src/components/app-shell.tsx web/src/components/primary-navigation.tsx web/src/i18n/dictionaries.json web/src/styles/dashboard.css web/tests
git commit -m "feat: add dense glass workspace shell"
```

## Task 3: Unify API states, loading and shared component states

**Files:**

- Modify: `web/src/components/api-state.tsx`
- Modify: `web/src/app/(dashboard)/loading.tsx`
- Modify: `web/src/app/(dashboard)/error.tsx`
- Modify: `web/src/styles/base.css`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write RED tests for the four shared states**

```js
test("shared route states reserve space and expose recovery semantics", async () => {
  const states = await source("src/components/api-state.tsx");
  const loading = await source("src/app/(dashboard)/loading.tsx");
  const error = await source("src/app/(dashboard)/error.tsx");
  assert.match(states, /state-panel--error/);
  assert.match(states, /state-panel--empty/);
  assert.match(states, /metric-card/);
  assert.match(loading, /route-skeleton/);
  assert.match(loading, /aria-hidden="true"/);
  assert.match(error, /role="alert"/);
  assert.match(error, /reset\(\)/);
});
```

- [ ] **Step 2: Run RED**

Run the UI redesign test. Expected: FAIL on `route-skeleton` and new state classes.

- [ ] **Step 3: Implement stable loading bounds**

`loading.tsx` renders one page heading skeleton, one metric row and one data surface skeleton. Do not render a changing loading sentence that shifts when data arrives:

```tsx
export default function Loading() {
  return <div aria-hidden="true" className="route-skeleton">
    <div className="skeleton skeleton-heading" />
    <div className="skeleton-metrics">
      {[0, 1, 2].map((index) => <div className="skeleton skeleton-metric" key={index} />)}
    </div>
    <div className="skeleton skeleton-surface" />
  </div>;
}
```

- [ ] **Step 4: Rename shared states without changing error payload content**

Use `state-panel state-panel--error`, `state-panel state-panel--empty`, and `metric-card`. Keep safe known-error mapping, HTTP status and code. Do not expose response bodies or stack traces.

- [ ] **Step 5: Add component state CSS**

Define default/hover/focus/active/disabled/loading priority for buttons and inputs. Use real `disabled`; keep `cursor:wait` only when `aria-busy="true"`, otherwise `not-allowed`.

- [ ] **Step 6: Run GREEN and commit**

Run targeted tests and typecheck, then:

```powershell
git add web/src/components/api-state.tsx 'web/src/app/(dashboard)/loading.tsx' 'web/src/app/(dashboard)/error.tsx' web/src/styles web/tests/ui-redesign.test.mjs
git commit -m "feat: unify dashboard route states"
```

## Task 4: Replace job cards with the data explorer and summary inspector

**Files:**

- Create: `web/src/lib/source-display.ts`
- Create: `web/tests/source-display.test.mjs`
- Modify: `web/src/components/job-list.tsx`
- Modify: `web/src/i18n/dictionaries.json`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write source display RED tests**

```js
test("collector source names become bounded presentation labels", async () => {
  const module = await import("../src/lib/source-display.ts");
  assert.equal(
    module.sourceDisplayName({ name: "Collector · www.topcv.vn [f1fe63e0]", url: "https://www.topcv.vn" }),
    "topcv.vn",
  );
  assert.equal(module.sourceDisplayName({ name: "NAVER Vietnam", url: "https://example.com" }), "NAVER Vietnam");
});
```

The repository uses Node 24, which executes erasable TypeScript in the Node test runner. Keep the helper in `source-display.ts`; do not create a JavaScript mirror.

- [ ] **Step 2: Run RED**

Run the new source-display test and UI redesign test. Expected: FAIL because helper/table/inspector do not exist.

- [ ] **Step 3: Implement the deterministic presentation helper**

```ts
export type SourceDisplayInput = { name: string; url: string };

export function sourceDisplayName(source: SourceDisplayInput): string {
  const collector = source.name
    .replace(/^Collector\s*·\s*/i, "")
    .replace(/\s*\[[0-9a-f]{8}\]\s*$/i, "")
    .replace(/^www\./i, "")
    .trim();
  if (collector && collector.length <= 48) return collector;
  try { return new URL(source.url).hostname.replace(/^www\./i, ""); }
  catch { return source.name.slice(0, 48); }
}
```

The UI must retain `title={job.source.name}` or equivalent accessible full value; the helper is presentation-only.

- [ ] **Step 4: Convert `JobList` to a client explorer using existing list data**

Add `"use client"`, `useState`, `useRef`, `useI18n`, and existing locale formatters. Render:

- a semantic table wrapper on desktop;
- title button opening inspector on desktop;
- a real `/jobs/{id}` link visible on mobile;
- company, level, status and source columns;
- selected job summary inspector with close button and full-detail link.

Do not fetch job detail from the client. Inspector fields are restricted to the existing `Job` object.

- [ ] **Step 5: Implement focus-safe close**

Store the triggering button in a ref. Escape closes the inspector and calls `.focus()` on that trigger. Use `aria-expanded`, `aria-controls`, `aria-labelledby`, and a close button with localized accessible label. Do not make the entire row a nested clickable container.

- [ ] **Step 6: Add VI/EN inspector strings**

Add `quickView`, `closeQuickView`, `openFullDetails`, `sourceLabel`, `statusLabel`, and `lastSeen` under both `jobs` dictionaries.

- [ ] **Step 7: Add responsive table rules**

At `<768px`, hide desktop title buttons and show direct job links; move company/source/date into the primary cell subtitle; remove inspector from layout. No document horizontal scroll is allowed.

- [ ] **Step 8: Run GREEN and commit**

Run source-display, UI, i18n, lint and typecheck gates, then:

```powershell
git add web/src/lib/source-display.ts web/src/components/job-list.tsx web/src/i18n/dictionaries.json web/src/styles/dashboard.css web/tests/source-display.test.mjs web/tests/ui-redesign.test.mjs web/tests/i18n.test.mjs
git commit -m "feat: add dense job explorer"
```

## Task 5: Migrate Overview, Jobs and Analytics archetypes

**Files:**

- Modify: `web/src/app/(dashboard)/page.tsx`
- Modify: `web/src/app/(dashboard)/jobs/page.tsx`
- Modify: `web/src/app/(dashboard)/analytics/page.tsx`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write route archetype RED tests**

Assert the pages expose `route-header`, `metrics-layout`, `explorer-toolbar`, `data-surface`, `comparison-list`, and `trend-table` instead of the old hero/dashboard-card hierarchy.

- [ ] **Step 2: Run RED**

Run the UI redesign test. Expected: FAIL on missing archetype classes.

- [ ] **Step 3: Migrate Overview**

Use this ordering:

```tsx
<section className="route-header route-header--compact">
  <p className="route-label">{dictionary.overview.eyebrow}</p>
  <h1>{dictionary.overview.title}</h1>
  <p>{dictionary.overview.body}</p>
</section>
<section className="metrics-layout" aria-label={dictionary.overview.title}>
  {sources.kind === "success"
    ? <Metric label={dictionary.overview.approvedSources} value={formatNumber(sources.value.data.filter((item) => item.approvalStatus === "approved").length, locale)} />
    : <Metric label={dictionary.overview.sources} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
  {skills.kind === "success"
    ? <Metric label={dictionary.overview.trackedSkills} value={formatNumber(skills.value.pagination.totalItems, locale)} note={`${dictionary.common.coverage} ${formatPercent(skills.value.meta.coverage, locale)}`} />
    : <Metric label={dictionary.overview.skills} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
  {jobs.kind === "success"
    ? <Metric label={dictionary.overview.visibleJobs} value={formatNumber(jobs.value.pagination.totalItems, locale)} />
    : <Metric label={dictionary.overview.jobs} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
</section>
<div className="overview-layout">
  <section className="glass-surface data-surface comparison-panel">
    <div className="section-heading"><h2>{dictionary.overview.demandTitle}</h2></div>
    <div className="comparison-list">{topSkills.map((skill) => <div className="comparison-row" key={skill.name}>{skill.name}</div>)}</div>
  </section>
  <section className="glass-surface data-surface activity-panel">
    <div className="section-heading"><h2>{dictionary.overview.latestTitle}</h2><Link href="/jobs">{dictionary.overview.explore}</Link></div>
    {jobs.kind === "success" ? <JobList jobs={jobs.value.data} /> : <ApiErrorState error={jobs} />}
  </section>
</div>
```

Keep current `Promise.all`, API calls, metric values and empty/error branches unchanged.

- [ ] **Step 4: Migrate Jobs**

Keep `query`, `location` and `page` parsing unchanged. The form becomes `explorer-toolbar glass-surface`; results use `data-surface` and `JobList`. Preserve GET form action `/jobs` and literal query behavior.

- [ ] **Step 5: Migrate Analytics**

Keep cohort/coverage calculations and dates unchanged. Skill frequency becomes direct-labeled comparison rows; trend remains a semantic table/list. Do not introduce a chart dependency or infer missing data.

- [ ] **Step 6: Run GREEN and commit**

Run UI/routes/i18n tests, lint and typecheck, then:

```powershell
git add 'web/src/app/(dashboard)/page.tsx' 'web/src/app/(dashboard)/jobs/page.tsx' 'web/src/app/(dashboard)/analytics/page.tsx' web/src/styles/dashboard.css web/tests/ui-redesign.test.mjs
git commit -m "feat: migrate dashboard data archetypes"
```

## Task 6: Migrate Crawler health and Sources operations

**Files:**

- Modify: `web/src/app/(dashboard)/crawler-health/page.tsx`
- Modify: `web/src/app/(dashboard)/sources/page.tsx`
- Modify: `web/src/components/ingestion-console.tsx`
- Modify: `web/src/components/source-recipe-panel.tsx`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/routes.test.mjs`
- Modify: `web/tests/source-recipes.test.mjs`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write RED operation-boundary tests**

Add assertions for `operations-workspace`, `operations-summary`, `operations-list`, `workflow-panel`, and `mapping-viewport`. Keep negative assertions that crawler health has no POST/run mutation and Source Recipe has no credential/proxy/bypass field.

- [ ] **Step 2: Run RED**

Run routes/source-recipes/UI tests. Expected: new classes fail; security negatives remain green.

- [ ] **Step 3: Migrate Crawler health presentation only**

Wrap health metrics, sources and run timeline in shared operations surfaces. Keep `loadSources`, `loadRuns`, all counters and read-only behavior unchanged.

- [ ] **Step 4: Add structural classes to SourceRecipePanel without refactoring logic**

The 593-line workflow stays one component in this task. Add classes around existing responsibilities:

```text
recipe inventory      -> operations-list
create/edit form      -> workflow-panel workflow-panel--form
preview candidates    -> workflow-panel workflow-panel--preview
route confirmation    -> state-panel state-panel--warning
visual mapper         -> workflow-panel workflow-panel--mapper
run/import history    -> workflow-panel workflow-panel--history
```

Do not rename API functions, timers, state fields, mutation handlers or mapping steps.

- [ ] **Step 5: Preserve bounded internal overflow**

`mapping-viewport` may scroll internally. `mapping-canvas` keeps its coordinate space. At `375px`, the document itself must not exceed the viewport; route proposal values use `overflow-wrap:anywhere`.

- [ ] **Step 6: Run GREEN and commit**

Run source recipe, routes, UI, lint and typecheck gates, then:

```powershell
git add 'web/src/app/(dashboard)/crawler-health/page.tsx' 'web/src/app/(dashboard)/sources/page.tsx' web/src/components/ingestion-console.tsx web/src/components/source-recipe-panel.tsx web/src/styles/dashboard.css web/tests/routes.test.mjs web/tests/source-recipes.test.mjs web/tests/ui-redesign.test.mjs
git commit -m "feat: migrate dashboard operations workspace"
```

## Task 7: Migrate Job detail, CV Match, Alerts, Privacy and Login

**Files:**

- Modify: `web/src/app/(dashboard)/jobs/[jobId]/page.tsx`
- Modify: `web/src/app/(dashboard)/cv-match/page.tsx`
- Modify: `web/src/app/(dashboard)/alerts/page.tsx`
- Modify: `web/src/app/(dashboard)/privacy/page.tsx`
- Modify: `web/src/app/login/page.tsx`
- Modify: `web/src/components/cv-match-panel.tsx`
- Modify: `web/src/components/alert-rules-panel.tsx`
- Modify: `web/src/components/login-form.tsx`
- Modify: `web/src/styles/dashboard.css`
- Modify: `web/tests/routes.test.mjs`
- Modify: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write RED class and boundary tests**

Assert `detail-inspector-page`, `workflow-layout`, `result-surface`, `policy-reader`, and `auth-surface`. Retain existing negative assertions for owner token, raw CV, webhook URL, mutation boundary and privacy truth fields.

- [ ] **Step 2: Run RED**

Run routes and UI tests. Expected: new visual classes fail; security contract assertions remain green.

- [ ] **Step 3: Migrate job detail to inspector-style page**

Keep `getJob`, `listJobChanges`, snapshot/provenance and description content unchanged. Use a high-opacity `data-surface` for description and a glass `detail-aside` for provenance/change history. Do not add client fetch or route interception.

- [ ] **Step 4: Migrate CV and Alerts workflows without behavior changes**

Use `workflow-layout`, `workflow-panel`, `result-surface`, `action-group` and semantic state classes. Keep resume limits/delete/match generation and alert create/dispatch/toggle/delete handlers byte-for-byte unless class placement requires formatting.

- [ ] **Step 5: Migrate Privacy and Login reading surfaces**

Privacy uses `policy-reader` with max line length `75ch` and high-opacity background. Login uses `auth-surface`; local no-login redirect and credential autocomplete remain unchanged.

- [ ] **Step 6: Run GREEN and commit**

Run routes/UI/i18n, lint and typecheck, then:

```powershell
git add 'web/src/app/(dashboard)/jobs/[jobId]/page.tsx' 'web/src/app/(dashboard)/cv-match/page.tsx' 'web/src/app/(dashboard)/alerts/page.tsx' 'web/src/app/(dashboard)/privacy/page.tsx' web/src/app/login/page.tsx web/src/components/cv-match-panel.tsx web/src/components/alert-rules-panel.tsx web/src/components/login-form.tsx web/src/styles/dashboard.css web/tests/routes.test.mjs web/tests/ui-redesign.test.mjs
git commit -m "feat: migrate dashboard workflow surfaces"
```

## Task 8: Run the complete browser matrix and repair verified defects

**Files:**

- Modify as defects require: `web/src/styles/*.css`, affected web component/page and its test
- Create local-only evidence under: `output/playwright/v6-022-dense-glass/`
- Create: `docs/evidence/V6-022-full-dashboard-dense-glass.md`

- [ ] **Step 1: Run complete web static/build gate**

```powershell
Set-Location web
npm run check
Set-Location ..
```

Expected: all web tests, ESLint, TypeScript and production build complete with exit `0`.

- [ ] **Step 2: Rebuild and restart only the web service**

Use the same env file that started the current Compose stack; do not replace `.env` or restart PostgreSQL/API unnecessarily:

```powershell
docker compose --env-file .env --profile crawler build web
docker compose --env-file .env --profile crawler up -d web --wait
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
```

If `.env` does not exist, use `.env.example` only after confirming the current launcher mode from `docker compose ps`/container environment. Do not guess credentials or deployment class.

- [ ] **Step 3: Capture the required visual matrix**

Use the existing local Python Playwright runtime or connected in-app browser. Check all routes:

```text
/
/jobs
/jobs/{one-current-job-id}
/analytics
/crawler-health
/sources
/cv-match
/alerts
/privacy
```

For VI and EN at widths `375`, `768`, `1024`, `1440`, record:

```js
({
  width: window.innerWidth,
  scrollWidth: document.documentElement.scrollWidth,
  clientWidth: document.documentElement.clientWidth,
  active: document.activeElement?.getAttribute("aria-label") ?? document.activeElement?.textContent,
})
```

Gate: `scrollWidth <= clientWidth` except approved internal mapping/table viewport; screenshot each route at `375` and `1440`.

- [ ] **Step 4: Verify interaction and accessibility**

Keyboard-only:

- skip link reaches `#main-content`;
- mobile nav opens, Escape closes and focus returns;
- job quick view opens, Escape closes and focus returns;
- form controls have visible labels/focus and `44px` targets;
- 200% zoom does not hide focus behind header/sidebar;
- reduced-motion removes ambient drift and shimmer without hiding content.

- [ ] **Step 5: Fix only observed defects with RED tests first**

For each failure, add the smallest source/contract test that reproduces it, run RED, patch the owning CSS/component, run GREEN, then rerun the affected browser cell. Do not bundle unrelated visual cleanup.

- [ ] **Step 6: Write evidence and commit**

Record exact test counts, build/smoke commands, viewport matrix, screenshot paths, glass fallback check, known untested boundary and Git SHA in `docs/evidence/V6-022-full-dashboard-dense-glass.md`. Commit evidence plus any final tested fixes.

```powershell
git add web docs/evidence/V6-022-full-dashboard-dense-glass.md
git commit -m "docs: record dense glass dashboard evidence"
```

## Task 9: Final verification, independent review and GitHub push

**Files:**

- Review all tracked changes from `b8d7667` to HEAD
- Do not add: `local-extension/**`, `note.md`, `TASK_BOARD.md`, `.superpowers/**`, `.npm-cache/**`, `output/**`

- [ ] **Step 1: Run fresh completion gates**

```powershell
Set-Location web
npm run check
Set-Location ..
.\scripts\web-smoke.ps1 -BaseUrl http://127.0.0.1:3000
.\scripts\scan-secrets.ps1
```

Expected: terminal success for every command; do not reuse Task 8 output as fresh evidence.

- [ ] **Step 2: Run repository privacy/leak gate**

```powershell
git check-ignore -v -- note.md TASK_BOARD.md local-extension\collector\manifest.json .superpowers\brainstorm\1258-1787733281\content\visual-system.html
git ls-files -- note.md TASK_BOARD.md 'local-extension/**' '.superpowers/**' 'output/**'
git diff --cached --name-only
git status --short --branch
```

Expected: private paths ignored, `git ls-files` empty for those paths, no accidental staged files, and only the pre-existing unrelated `.npm-cache/` may remain untracked.

- [ ] **Step 3: Request independent code review**

Use `superpowers:requesting-code-review` against the merge base. Review must inspect shared CSS token use, keyboard behavior, source-policy/CV/privacy regressions and route coverage. Fix Important/Critical findings with TDD; document lower-risk follow-ups only when genuinely out of scope.

- [ ] **Step 4: Verify final diff is lean**

```powershell
git diff --stat main...HEAD
git diff --check main...HEAD
git log --oneline main..HEAD
```

Reject hard-coded per-page duplicate glass colors, unused selectors, new dependencies, API changes and speculative Telegram UI.

- [ ] **Step 5: Push the verified web branch**

The owner explicitly authorized GitHub push for this web redesign:

```powershell
git push -u origin codex/full-dashboard-g2-redesign
```

Do not merge to `main` until the finishing workflow confirms the integration choice. Do not push any extension reference in commit messages, PR body or public evidence.
