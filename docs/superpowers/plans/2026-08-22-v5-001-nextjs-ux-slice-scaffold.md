# V5-001 Next.js UX Slice and Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tạo một Next.js App Router scaffold trong `web/` với sáu route trung thực, route/API manifest được test và command surface build được.

**Architecture:** Next.js là presentation boundary trong cùng repository; Server Components là mặc định và FastAPI/OpenAPI tiếp tục là backend contract duy nhất. V5-001 chưa fetch data, không tạo BFF và không đoán ResumeProfile/JobMatch schema.

**Tech Stack:** Node 24.11.1, npm 11.6.2, Next.js 16.3.2, React 19.2.8, TypeScript 5.9.3, ESLint 10.9.0, native CSS, Node built-in test runner.

---

### Task 1: Prove the route contract is missing

**Files:**

- Create: `web/tests/routes.test.mjs`

- [ ] **Step 1: Write the failing contract test**

```javascript
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { access } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
const manifestUrl = new URL("src/contracts/routes.json", webRoot);

const expected = [
  ["overview", "/", "scaffolded", true],
  ["jobs", "/jobs", "scaffolded", true],
  ["job-detail", "/jobs/[jobId]", "scaffolded", false],
  ["analytics", "/analytics", "scaffolded", true],
  ["crawler-health", "/crawler-health", "scaffolded", true],
  ["cv-match", "/cv-match", "backend_not_ready", true],
];

test("route manifest owns the exact V5-001 surface", async () => {
  const routes = JSON.parse(await readFile(manifestUrl, "utf8"));
  assert.deepEqual(
    routes.map(({ id, path, availability, showInNav }) => [
      id,
      path,
      availability,
      showInNav,
    ]),
    expected,
  );
  assert.equal(new Set(routes.map(({ id }) => id)).size, routes.length);
  assert.equal(new Set(routes.map(({ path }) => path)).size, routes.length);
  assert.equal(new Set(routes.map(({ pageFile }) => pageFile)).size, routes.length);
  for (const route of routes) {
    await access(new URL(route.pageFile, webRoot));
  }
  assert.deepEqual(routes.at(-1).apiResources, []);
  assert.equal(routes.filter(({ showInNav }) => showInNav).length, 5);
});
```

- [ ] **Step 2: Run RED**

```powershell
node --test web/tests/routes.test.mjs
```

Expected: FAIL with `ENOENT` for `web/src/contracts/routes.json`.

- [ ] **Step 3: Commit the observed test only after GREEN in Task 3**

Do not commit a knowingly failing repository state.

### Task 2: Add exact frontend configuration

**Files:**

- Create: `web/package.json`
- Create: `web/package-lock.json` via npm
- Create: `web/tsconfig.json`
- Create: `web/eslint.config.mjs`
- Create: `web/next-env.d.ts`
- Create: `web/.env.example`

- [ ] **Step 1: Add package and TypeScript config**

`package.json` must contain exact versions and scripts:

```json
{
  "name": "devradar-web",
  "version": "0.1.0",
  "private": true,
  "engines": { "node": ">=20.9.0" },
  "packageManager": "npm@11.6.2",
  "scripts": {
    "dev": "next dev --hostname 127.0.0.1",
    "build": "next build",
    "start": "next start --hostname 127.0.0.1",
    "test": "node --test tests/*.test.mjs",
    "lint": "eslint .",
    "lint:fix": "eslint . --fix",
    "typecheck": "tsc --noEmit",
    "check": "npm run test && npm run lint && npm run typecheck && npm run build"
  },
  "dependencies": {
    "next": "16.3.2",
    "react": "19.2.8",
    "react-dom": "19.2.8"
  },
  "devDependencies": {
    "@types/node": "24.13.3",
    "@types/react": "19.2.18",
    "@types/react-dom": "19.2.4",
    "eslint": "10.9.0",
    "eslint-config-next": "16.3.2",
    "typescript": "5.9.3"
  }
}
```

Use strict TypeScript, `moduleResolution: bundler`, `resolveJsonModule`, Next plugin and `@/* → ./src/*`. ESLint must spread `core-web-vitals` and `typescript` flat configs exactly as the official Next 16 guide.

`web/.env.example`:

```dotenv
DEVRADAR_API_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 2: Generate the npm lock**

```powershell
Set-Location web
npm install --ignore-scripts
npm ls --depth=0
Set-Location ..
```

Expected: exact direct dependencies resolve with no missing/invalid package. `--ignore-scripts` keeps install bounded; Next does not require a postinstall for this scaffold.

### Task 3: Implement the manifest and route scaffold

**Files:**

- Create: `web/src/contracts/routes.json`
- Create: `web/src/app/layout.tsx`
- Create: `web/src/app/globals.css`
- Create: `web/src/app/(dashboard)/layout.tsx`
- Create: `web/src/app/(dashboard)/page.tsx`
- Create: `web/src/app/(dashboard)/jobs/page.tsx`
- Create: `web/src/app/(dashboard)/jobs/[jobId]/page.tsx`
- Create: `web/src/app/(dashboard)/analytics/page.tsx`
- Create: `web/src/app/(dashboard)/crawler-health/page.tsx`
- Create: `web/src/app/(dashboard)/cv-match/page.tsx`
- Create: `web/src/components/app-shell.tsx`
- Create: `web/src/components/route-placeholder.tsx`

- [ ] **Step 1: Add exact manifest data**

```json
[
  {
    "id": "overview",
    "path": "/",
    "pageFile": "src/app/(dashboard)/page.tsx",
    "label": "Overview",
    "description": "Market, inventory, source-health and skill signals in one evidence-first view.",
    "availability": "scaffolded",
    "showInNav": true,
    "apiResources": ["GET /api/v1/health", "GET /api/v1/jobs", "GET /api/v1/sources", "GET /api/v1/skills"]
  },
  {
    "id": "jobs",
    "path": "/jobs",
    "pageFile": "src/app/(dashboard)/jobs/page.tsx",
    "label": "Jobs",
    "description": "Explore canonical jobs with stable filters, provenance and pagination.",
    "availability": "scaffolded",
    "showInNav": true,
    "apiResources": ["GET /api/v1/jobs"]
  },
  {
    "id": "job-detail",
    "path": "/jobs/[jobId]",
    "pageFile": "src/app/(dashboard)/jobs/[jobId]/page.tsx",
    "label": "Job detail",
    "description": "Inspect one canonical job, its source provenance and change history.",
    "availability": "scaffolded",
    "showInNav": false,
    "apiResources": ["GET /api/v1/jobs/{jobId}", "GET /api/v1/jobs/{jobId}/changes"]
  },
  {
    "id": "analytics",
    "path": "/analytics",
    "pageFile": "src/app/(dashboard)/analytics/page.tsx",
    "label": "Analytics",
    "description": "Read skill frequency and trend data with cohort size and extraction coverage.",
    "availability": "scaffolded",
    "showInNav": true,
    "apiResources": ["GET /api/v1/skills", "GET /api/v1/skill-trends"]
  },
  {
    "id": "crawler-health",
    "path": "/crawler-health",
    "pageFile": "src/app/(dashboard)/crawler-health/page.tsx",
    "label": "Crawler health",
    "description": "Review approved source health, coverage signals and crawl history.",
    "availability": "scaffolded",
    "showInNav": true,
    "apiResources": ["GET /api/v1/sources", "GET /api/v1/crawl-runs"]
  },
  {
    "id": "cv-match",
    "path": "/cv-match",
    "pageFile": "src/app/(dashboard)/cv-match/page.tsx",
    "label": "CV match",
    "description": "Prepare the local-only entry point for secure CV matching.",
    "availability": "backend_not_ready",
    "showInNav": true,
    "apiResources": []
  }
]
```

- [ ] **Step 2: Add the shared Server Component shell**

```tsx
import Link from "next/link";
import type { ReactNode } from "react";
import routes from "@/contracts/routes.json";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="site-header">
        <div>
          <Link className="brand" href="/">DevRadar</Link>
          <p className="eyebrow">Vietnam IT market evidence</p>
        </div>
        <span className="phase-badge">V5 scaffold</span>
      </header>
      <nav aria-label="Primary navigation" className="primary-nav">
        {routes.filter((route) => route.showInNav).map((route) => (
          <Link href={route.path} key={route.id}>{route.label}</Link>
        ))}
      </nav>
      <main id="main-content">{children}</main>
    </div>
  );
}
```

- [ ] **Step 3: Add the truthful placeholder component**

```tsx
import routes from "@/contracts/routes.json";

export function RoutePlaceholder({ routeId, context }: { routeId: string; context?: string }) {
  const route = routes.find((candidate) => candidate.id === routeId);
  if (!route) throw new Error("Unknown route contract.");
  return (
    <section className="route-panel">
      <p className="status-line">{route.availability.replaceAll("_", " ")}</p>
      <h1>{route.label}</h1>
      <p className="route-description">{route.description}</p>
      {context ? <p className="route-context">{context}</p> : null}
      <h2>Data contract</h2>
      {route.apiResources.length ? (
        <ul>{route.apiResources.map((resource) => <li key={resource}><code>{resource}</code></li>)}</ul>
      ) : (
        <p>Backend contract is intentionally not available yet.</p>
      )}
      <p className="handoff">Data rendering starts in the phase named by this route&apos;s availability.</p>
    </section>
  );
}
```

- [ ] **Step 4: Add all route pages**

Root files:

```tsx
// src/app/layout.tsx
import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "DevRadar", template: "%s | DevRadar" },
  description: "Evidence-first job market intelligence for Vietnam IT roles.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="vi"><body>{children}</body></html>;
}

// src/app/(dashboard)/layout.tsx
import type { ReactNode } from "react";
import { AppShell } from "@/components/app-shell";
export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
```

Static pages:

```tsx
// page.tsx variants use the matching routeId
import { RoutePlaceholder } from "@/components/route-placeholder";
export default function OverviewPage() { return <RoutePlaceholder routeId="overview" />; }
export function JobsPage() { return <RoutePlaceholder routeId="jobs" />; }
export function AnalyticsPage() { return <RoutePlaceholder routeId="analytics" />; }
export function CrawlerHealthPage() { return <RoutePlaceholder routeId="crawler-health" />; }
export function CvMatchPage() { return <RoutePlaceholder routeId="cv-match" />; }
```

Write each named function as the default export in its own exact `page.tsx`. Dynamic detail uses:

```tsx
export default async function JobDetailPage({
  params,
}: {
  params: Promise<{ jobId: string }>;
}) {
  const { jobId } = await params;
  return <RoutePlaceholder context={`Requested job ID: ${jobId}`} routeId="job-detail" />;
}
```

Root layout sets `lang="vi"`, imports `globals.css` and declares metadata. Dashboard layout only wraps children in `AppShell`; no client component is needed.

- [ ] **Step 5: Add restrained native CSS**

```css
:root { color-scheme: light dark; --bg:#f4f1e8; --surface:#fffdf7; --text:#17211b; --muted:#607067; --line:#cbd3ca; --accent:#176b4d; }
@media (prefers-color-scheme: dark) { :root { --bg:#101713; --surface:#18211c; --text:#edf4ef; --muted:#aab8af; --line:#34433a; --accent:#67d5a7; } }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text); font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }
a { color:inherit; }
a:focus-visible { outline:3px solid var(--accent); outline-offset:4px; }
.app-shell { width:min(1120px,calc(100% - 2rem)); margin:0 auto; padding:1.5rem 0 4rem; }
.site-header { display:flex; align-items:flex-start; justify-content:space-between; gap:1rem; border-bottom:1px solid var(--line); padding-bottom:1rem; }
.brand { font-size:1.4rem; font-weight:750; text-decoration:none; }
.eyebrow,.status-line { color:var(--muted); font-size:.78rem; letter-spacing:.08em; margin:.3rem 0 0; text-transform:uppercase; }
.phase-badge { border:1px solid var(--line); border-radius:999px; padding:.35rem .65rem; white-space:nowrap; }
.primary-nav { display:flex; flex-wrap:wrap; gap:.5rem 1rem; padding:1rem 0; }
.primary-nav a { text-underline-offset:.25rem; }
.route-panel { background:var(--surface); border:1px solid var(--line); padding:clamp(1.25rem,4vw,3rem); }
.route-panel h1 { font-size:clamp(2rem,7vw,4.5rem); letter-spacing:-.045em; line-height:1; margin:.6rem 0 1rem; }
.route-description { color:var(--muted); font-size:1.1rem; max-width:65ch; }
.route-context,.handoff { border-left:3px solid var(--accent); padding-left:.8rem; }
code { overflow-wrap:anywhere; }
@media (max-width:560px) { .site-header { align-items:flex-start; flex-direction:column; } .app-shell { width:min(100% - 1rem,1120px); } }
```

- [ ] **Step 6: Run GREEN**

```powershell
node --test web/tests/routes.test.mjs
```

Expected: `1` test pass.

- [ ] **Step 7: Commit scaffold**

```powershell
git add web
git commit -m "feat: scaffold v5 nextjs routes"
```

### Task 4: Verify the frontend as an isolated boundary

- [ ] **Step 1: Run the complete frontend gate**

```powershell
Set-Location web
npm run check
npm audit --audit-level=high
Set-Location ..
```

Expected: Node test, ESLint, TypeScript and production build pass; audit has no high/critical vulnerability. Build output lists `/`, `/jobs`, `/jobs/[jobId]`, `/analytics`, `/crawler-health`, `/cv-match` and no `/api` route.

- [ ] **Step 2: Run local HTTP smoke**

Start `npm run dev` from `web/` in an exec session, wait for ready output, then request:

```powershell
'/', '/jobs', '/jobs/test-job-id', '/analytics', '/crawler-health', '/cv-match' |
    ForEach-Object { (Invoke-WebRequest "http://127.0.0.1:3000$_").StatusCode }
```

Expected: six `200` statuses. Stop the dev session with `Ctrl+C`; do not leave a background process.

- [ ] **Step 3: Run backend regression and boundary scans**

```powershell
.venv\Scripts\python -m pytest
rg -n "NEXT_PUBLIC_|src/app/api|route\.ts|tailwind|zustand|swr|react-query" web
git diff --check
```

Expected: backend default suite passes; boundary scan has no source/config dependency hits (lock metadata may contain transitive names and must be reviewed, not blindly treated as code use).

### Task 5: Document evidence and open V5-002

**Files:**

- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/ROADMAP.md`
- Create: `docs/evidence/V5-001-nextjs-ux-slice-scaffold.md`
- Modify: local ignored `TASK_BOARD.md`

- [ ] **Step 1: Add verified commands only**

README/AGENTS add:

```powershell
Set-Location web
npm install
npm run dev
npm run check
Set-Location ..
```

State local bind `127.0.0.1:3000`, exact Node/npm used and that scaffold does not need backend/network during check. Do not claim data views exist.

- [ ] **Step 2: Update architecture and roadmap**

Architecture records `web/` App Router presentation boundary, Server Components default, no BFF/current API call. Roadmap sets V5 `in_progress`, records V5-001 scaffold evidence and keeps every later V5 capability proposed.

- [ ] **Step 3: Write evidence from actual outputs**

Record RED `ENOENT`, GREEN count, exact package versions, npm check/audit, route build list, six HTTP statuses, backend pytest, Markdown counts, no-BFF/public-env scan and official Next.js source URLs.

- [ ] **Step 4: Update ignored board**

Set V5-001 `Done`, V5-002 `Ready`, active phase V5 `in_progress`. Verify `git check-ignore -v TASK_BOARD.md`; never stage it.

- [ ] **Step 5: Final verification and closeout commit**

Run `npm run check`, backend default pytest, Markdown scanner, `git diff --check`, dependency diff review and `git status`. Then:

```powershell
git add README.md AGENTS.md docs
git commit -m "docs: close v5-001 nextjs scaffold"
```

Do not push until the user-requested phase push gate or a separate explicit checkpoint; V5 remains in progress.
