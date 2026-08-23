# DevRadar Web Modern Light Editorial Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle every existing DevRadar dashboard route into the approved Modern Light SaaS system with editorial headings while preserving route, API, auth, privacy, upload and operator behavior.

**Architecture:** Keep the existing Next.js App Router and CSS-native component styling. Introduce shared visual tokens and semantic primitives in `globals.css`, then update the shell, page sections and existing interactive components to consume those classes. No new runtime dependency, API field, route or client-state layer is introduced.

**Tech Stack:** Next.js `16.3.2`, React `19.2.8`, TypeScript `5.9.3`, native CSS, existing Node test/lint/typecheck/build scripts.

---

## File map and ownership

- Modify `web/src/app/globals.css`: single light theme tokens, typography, shared surfaces, responsive rules, focus/motion/accessibility styles.
- Modify `web/src/components/app-shell.tsx`: shell markup, brand mark, navigation/auth grouping; preserve `routes.json` and auth calls.
- Modify `web/src/components/api-state.tsx`: shared Metric, Error, Empty and status visual primitives; preserve messages/roles.
- Modify `web/src/components/job-list.tsx`: job card markup and source/salary/level hierarchy; preserve all job fields and links.
- Modify `web/src/components/cv-match-panel.tsx`: upload/profile/match grouping and semantic classes; preserve FormData, session request, delete and match calls.
- Modify `web/src/components/alert-rules-panel.tsx`: rule builder/list grouping and action classes; preserve CSRF and owner APIs.
- Modify `web/src/components/ingestion-console.tsx`: source health/history grouping and status classes; preserve bounded polling and run action.
- Modify route pages under `web/src/app/(dashboard)/`: adjust section wrappers/headings/classes only for overview, jobs, job detail, analytics, CV match, alerts, crawler health and privacy.
- Create `web/tests/ui-redesign.test.mjs`: contract checks for light tokens, route surface class usage, no old green palette and preserved safety-sensitive strings.
- Modify `.gitignore`: ignore `.superpowers/` visual-companion session artifacts.

## Task 1: Add failing visual contract tests

**Files:**
- Create: `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Write failing contract tests**

```js
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
async function source(path) { return readFile(new URL(path, webRoot), "utf8"); }

test("light editorial token contract is present and old green theme is gone", async () => {
  const css = await source("src/app/globals.css");
  assert.match(css, /--bg:\s*#F6F8FC/i);
  assert.match(css, /--accent:\s*#4F46E5/i);
  assert.match(css, /Georgia/);
  assert.doesNotMatch(css, /--bg:#f4f1e8/);
  assert.doesNotMatch(css, /prefers-color-scheme:\s*dark/);
});

test("shared shell and route surfaces use redesign primitives", async () => {
  const shell = await source("src/components/app-shell.tsx");
  const overview = await source("src/app/(dashboard)/page.tsx");
  const jobs = await source("src/components/job-list.tsx");
  assert.match(shell, /brand-mark/);
  assert.match(shell, /nav-group/);
  assert.match(overview, /dashboard-grid/);
  assert.match(jobs, /job-card/);
});

test("redesign preserves CV, crawler and privacy boundaries", async () => {
  const cv = await source("src/components/cv-match-panel.tsx");
  const crawler = await source("src/components/ingestion-console.tsx");
  const privacy = await source("src/app/(dashboard)/privacy/page.tsx");
  assert.match(cv, /MAX_RESUME_BYTES/);
  assert.match(cv, /deleteResume/);
  assert.match(crawler, /POLL_WINDOW_MS\s*=\s*30_000/);
  assert.match(crawler, /approvalStatus/);
  assert.match(privacy, /GeoComply|Lever/);
});
```

- [ ] **Step 2: Run the new tests and verify the expected failure**

Run from `web/`:

```powershell
npm test -- --test-name-pattern="light editorial|shared shell|redesign preserves"
```

Expected: FAIL because the old palette and new class contracts do not exist yet.

- [ ] **Step 3: Commit the failing test contract**

```powershell
git add web/tests/ui-redesign.test.mjs
git commit -m "test: define light editorial web contract"
```

## Task 2: Replace global visual tokens and shared primitives

**Files:**
- Modify: `web/src/app/globals.css`
- Modify: `web/src/components/api-state.tsx`

- [ ] **Step 1: Replace the old root tokens with the approved light palette**

Use this root contract at the start of `globals.css`:

```css
:root {
  color-scheme: light;
  --bg: #f6f8fc;
  --surface: #ffffff;
  --surface-subtle: #eef2f8;
  --text: #132039;
  --muted: #69758b;
  --line: #dfe6f1;
  --accent: #4f46e5;
  --accent-soft: #eef2ff;
  --cyan: #0891b2;
  --success: #059669;
  --success-soft: #ecfdf5;
  --warning: #d97706;
  --warning-soft: #fffbeb;
  --danger: #b42318;
  --danger-soft: #fef3f2;
  --radius-panel: 12px;
  --radius-feature: 16px;
  --radius-pill: 999px;
  --shadow-soft: 0 12px 28px rgb(19 32 57 / 0.08);
  --focus-ring: 0 0 0 3px rgb(79 70 229 / 0.25);
}
```

Add explicit `:focus-visible`, `prefers-reduced-motion`, typography and mobile overflow rules. Remove the dark media query and old green token values.

- [ ] **Step 2: Add semantic shared surface classes**

Add `.surface`, `.content-section`, `.metric-grid`, `.metric`, `.section-heading`, `.api-state`, `.status-message`, `.badge`, `.button-primary`, `.button-secondary`, `.button-danger`, `.field-help`, `.empty-state`, `.loading-state` and responsive variants. Use `border-radius: var(--radius-panel)` and preserve focus styles.

- [ ] **Step 3: Normalize API state component class names without changing output semantics**

Update `Metric`, `ApiErrorState` and `EmptyState` to keep existing text, `role="alert"` and values while adding `metric-card`, `api-state--error` and `api-state--empty` classes. Keep `ApiFailure` unchanged.

- [ ] **Step 4: Run focused tests**

```powershell
npm test -- --test-name-pattern="light editorial"
```

Expected: token assertions pass; route class assertions still fail.

- [ ] **Step 5: Commit the visual foundation**

```powershell
git add web/src/app/globals.css web/src/components/api-state.tsx
git commit -m "style: add light editorial visual foundation"
```

## Task 3: Redesign shell and overview route

**Files:**
- Modify: `web/src/components/app-shell.tsx`
- Modify: `web/src/app/(dashboard)/page.tsx`

- [ ] **Step 1: Add semantic shell groups while preserving navigation source**

Keep `routes.filter((route) => route.showInNav)` and `AuthControls`. Add `brand-mark`, `brand-copy`, `nav-group` and `header-actions` wrappers; do not hardcode or rename route links.

- [ ] **Step 2: Add overview composition classes**

Keep the existing three API calls and conditional states. Add `dashboard-grid`, `dashboard-chart-panel`, `dashboard-feed-panel` and `kpi-grid` wrappers around existing metrics and `JobList`. Do not invent chart data or change counts.

- [ ] **Step 3: Verify shell and route safety**

```powershell
npm test -- --test-name-pattern="route manifest|privacy route|light editorial|shared shell"
```

Expected: route/API safety tests pass and new shell/overview assertions pass.

- [ ] **Step 4: Commit shell and overview**

```powershell
git add web/src/components/app-shell.tsx "web/src/app/(dashboard)/page.tsx"
git commit -m "style: redesign dashboard shell and overview"
```

## Task 4: Redesign job explorer and job detail

**Files:**
- Modify: `web/src/components/job-list.tsx`
- Modify: `web/src/app/(dashboard)/jobs/page.tsx`
- Modify: `web/src/app/(dashboard)/jobs/[jobId]/page.tsx`

- [ ] **Step 1: Convert job row markup to a responsive card**

Keep `Job` fields and links. Add `job-card`, `job-card-main`, `job-card-meta`, `source-badge`, `salary-badge` and `level-list` classes. Render raw salary unchanged and keep source/date visible.

- [ ] **Step 2: Add explorer filter surface classes without changing query parameters**

Keep `query`, `location`, `page`, `listJobs` and input names. Wrap the form in `jobs-toolbar` and use `input-shell`/`button-primary` classes.

- [ ] **Step 3: Add detail layout classes**

Keep `getJob`, `listJobChanges`, original source link, parse status and change history. Add `detail-main`, `detail-aside`, `provenance-card` and `change-list` classes. Keep the back link accessible.

- [ ] **Step 4: Run jobs tests and typecheck**

```powershell
npm test -- --test-name-pattern="route manifest|job"
npm run typecheck
```

Expected: PASS with no API/resource changes.

- [ ] **Step 5: Commit jobs surfaces**

```powershell
git add web/src/components/job-list.tsx "web/src/app/(dashboard)/jobs/page.tsx" "web/src/app/(dashboard)/jobs/[jobId]/page.tsx"
git commit -m "style: redesign jobs explorer and detail"
```

## Task 5: Redesign analytics and privacy surfaces

**Files:**
- Modify: `web/src/app/(dashboard)/analytics/page.tsx`
- Modify: `web/src/app/(dashboard)/privacy/page.tsx`

- [ ] **Step 1: Add analytics panel classes while preserving denominator copy**

Keep `listSkills`, `listSkillTrends`, cohort metrics, date window, category, job count, share, denominator and coverage text. Add `analytics-grid`, `skill-table`, `trend-list`, `cohort-note` and `period-note` classes.

- [ ] **Step 2: Add privacy editorial grouping**

Keep `getPrivacy`, policy version, retention facts, AI boundary, source allow-list and GeoComply/Lever permission-required text. Add `policy-callout`, `policy-list` and `policy-section` classes only.

- [ ] **Step 3: Run analytics/privacy tests**

```powershell
npm test -- --test-name-pattern="privacy route|route manifest"
npm run lint
```

Expected: PASS with policy strings and route manifest unchanged.

- [ ] **Step 4: Commit analytics and privacy**

```powershell
git add "web/src/app/(dashboard)/analytics/page.tsx" "web/src/app/(dashboard)/privacy/page.tsx"
git commit -m "style: redesign analytics and privacy surfaces"
```

## Task 6: Redesign CV match surface

**Files:**
- Modify: `web/src/app/(dashboard)/cv-match/page.tsx`
- Modify: `web/src/components/cv-match-panel.tsx`

- [ ] **Step 1: Add protected upload card classes without changing file handling**

Keep `FormData`, `MAX_RESUME_BYTES`, PDF/DOCX accept list, session APIs, TTL text and original-file deletion notice. Add `cv-upload-card`, `upload-dropzone`, `profile-card` and `privacy-note` classes around existing controls.

- [ ] **Step 2: Add score tile and skill evidence classes**

Keep `percent`, `JobMatch`, `matchedSkills`, `missingSkills`, `evidenceCoverage`, scoring version, refresh and delete behavior. Add `score-tile`, `evidence-meta`, `skill-columns`, `matched-skills`, `missing-skills` classes. Use text/number hierarchy rather than a probability-style progress ring.

- [ ] **Step 3: Run CV safety tests**

```powershell
npm test -- --test-name-pattern="cv match|light editorial|redesign preserves"
npm run typecheck
```

Expected: PASS; no `localStorage`, owner header, API resource or upload limit change.

- [ ] **Step 4: Commit CV surface**

```powershell
git add "web/src/app/(dashboard)/cv-match/page.tsx" web/src/components/cv-match-panel.tsx
git commit -m "style: redesign protected CV matching surface"
```

## Task 7: Redesign alerts and crawler health surfaces

**Files:**
- Modify: `web/src/components/alert-rules-panel.tsx`
- Modify: `web/src/components/ingestion-console.tsx`
- Modify: `web/src/app/(dashboard)/alerts/page.tsx`
- Modify: `web/src/app/(dashboard)/crawler-health/page.tsx`

- [ ] **Step 1: Add alert builder and rule card classes**

Keep all existing input IDs, validation, `createAlertRule`, `dispatchAlertRule`, enable/delete actions, notices and CSRF/session APIs. Add `alert-intro`, `rule-builder`, `rule-card`, `rule-actions` and `channel-badge` classes.

- [ ] **Step 2: Add crawler source health and history classes**

Keep `POLL_INTERVAL_MS`, `POLL_WINDOW_MS`, terminal status set, `approvalStatus`, `requestCrawlRun`, `getIngestionRun` and status messages. Add `health-grid`, `source-card`, `health-status`, `run-timeline` and `run-card` classes. Pair each status color with text.

- [ ] **Step 3: Run alert/crawler tests**

```powershell
npm test -- --test-name-pattern="alert|crawler|redesign preserves"
npm run lint
```

Expected: PASS; bounded polling and approved-source restrictions remain intact.

- [ ] **Step 4: Commit alert and crawler surfaces**

```powershell
git add web/src/components/alert-rules-panel.tsx web/src/components/ingestion-console.tsx "web/src/app/(dashboard)/alerts/page.tsx" "web/src/app/(dashboard)/crawler-health/page.tsx"
git commit -m "style: redesign alerts and crawler health"
```

## Task 8: Full verification and browser smoke

**Files:**
- Modify: no source files unless verification finds a concrete regression.
- Test: `web/tests/routes.test.mjs`, `web/tests/ui-redesign.test.mjs`

- [ ] **Step 1: Run the complete web gate**

```powershell
npm run check
```

Expected: tests, ESLint, TypeScript and Next build all exit `0`.

- [ ] **Step 2: Run local browser smoke**

Exercise `/login`, `/`, `/jobs?query=Python&location=Ho%20Chi%20Minh`, `/jobs/<known-id>`, `/analytics`, `/cv-match`, `/alerts`, `/crawler-health` and `/privacy`. Verify desktop and 320px mobile layouts, no horizontal overflow, visible keyboard focus and usable loading/error/empty/status states.

- [ ] **Step 3: Run final diff and security boundary audit**

```powershell
git diff --check HEAD~7..HEAD
rg -n "X-DevRadar-Owner|localStorage|webhookUrl|owner token" web/src/components web/src/lib
git status --short --branch
```

Expected: no new owner-token/localStorage/webhook exposure, no whitespace errors, and only intended frontend/docs changes.

- [ ] **Step 4: Push and record exact CI evidence**

```powershell
git push origin main
```

Record the exact CI run URL/SHA in the handoff. Do not mark a product phase complete from visual checks alone.

## Plan self-review

- Covers all design spec sections: tokens, shell, eight route surfaces, responsive, accessibility, states, no dependencies and verification.
- No route/API/auth/privacy contract changes are planned.
- No unresolved placeholders or future dependency work are included.
- Safety-sensitive terms and exact existing function boundaries are named in the relevant task before styling.
