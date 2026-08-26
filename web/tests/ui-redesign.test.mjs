import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
async function source(path) { return readFile(new URL(path, webRoot), "utf8"); }
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

test("document does not force horizontal overflow at a 320px viewport", async () => {
  const css = await cssBundle();
  assert.doesNotMatch(css, /html\{[^}]*min-width:\s*320px/);
});

test("readable type scale, controls and navigation are bounded", async () => {
  const css = await cssBundle();

  assert.match(css, /--font-ui:\s*ui-sans-serif,\s*system-ui,\s*-apple-system,\s*"Segoe UI",\s*sans-serif/);
  assert.match(css, /--text-xs:\s*\.8125rem/);
  assert.match(css, /--control-min-height:\s*44px/);
  assert.match(css, /font-size:clamp\(1\.75rem,3vw,2\.25rem\)/);
  assert.match(css, /line-height:1\.12/);
  assert.match(css, /letter-spacing:-\.035em/);
  assert.doesNotMatch(css, /15vw|font-size:clamp\(2\.65rem,7vw,5\.4rem\)/);
  assert.doesNotMatch(css, /\.nav-links\{[^}]*flex-wrap:wrap/);
  assert.match(css, /\.nav-links a\[aria-current="page"\]/);
  assert.match(css, /\.nav-toggle\{[^}]*min-width:44px/);
  assert.doesNotMatch(css, /\.primary-nav\{[^}]*overflow-x:auto/);
});

test("route grids reflow before content creates document overflow", async () => {
  const css = await cssBundle();

  assert.match(css, /@media\(max-width:960px\)/);
  assert.match(css, /\.dashboard-grid,\.detail-grid,\.analytics-grid,\.cv-layout\{grid-template-columns:1fr\}/);
  assert.match(css, /\.analytics-grid>\*,\.dashboard-grid>\*,\.detail-grid>\*,\.cv-layout>\*\{min-width:0\}/);
  assert.match(css, /\.skill-row,\.trend-row\{flex-wrap:wrap\}/);
  assert.match(css, /\.description-text,\.policy-list\{max-width:75ch\}/);
  assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /\.kpi-grid,\.metric-grid,\.health-grid\{grid-template-columns:1fr\}/);
  assert.ok(
    css.lastIndexOf("@media(max-width:960px)") > css.indexOf(".source-recipe-layout{"),
    "the source-recipe base rule must precede its responsive override",
  );
});

test("app metadata includes a local brand icon", async () => {
  const iconPath = new URL("src/app/icon.svg", webRoot);
  await access(iconPath);
  const icon = await readFile(iconPath, "utf8");
  assert.match(icon, /#4F46E5/i);
  assert.match(icon, /viewBox="0 0 64 64"/);
});

test("source recipe mapper stays operable at narrow widths", async () => {
  const css = await cssBundle();
  const panel = await source("src/components/source-recipe-panel.tsx");

  assert.match(css, /\.source-recipe-layout\{[^}]*grid-template-columns/);
  assert.match(css, /\.mapping-viewport\{[^}]*overflow:auto/);
  assert.match(css, /\.mapping-overlay-button\{[^}]*min-width:44px[^}]*min-height:44px/);
  assert.match(css, /@media\(max-width:420px\)/);
  assert.match(css, /\.source-recipe-layout[^}]*grid-template-columns:1fr/);
  assert.match(panel, /aria-label/);
  assert.match(panel, /aria-pressed/);
});

test("source route confirmation is readable and operable on narrow screens", async () => {
  const css = await cssBundle();
  assert.match(css, /\.route-proposal-card\{[^}]*display:grid/);
  assert.match(css, /\.route-proposal-value\{[^}]*overflow-wrap:anywhere/);
  assert.match(css, /@media\(max-width:420px\)[\s\S]*\.route-proposal-card[^}]*padding/);
});

test("shared shell and route surfaces use redesign primitives", async () => {
  const shell = await source("src/components/app-shell.tsx");
  const overview = await source("src/app/(dashboard)/page.tsx");
  const jobs = await source("src/components/job-list.tsx");
  assert.match(shell, /brand-mark/);
  assert.match(shell, /PrimaryNavigation/);
  assert.match(overview, /overview-layout/);
  assert.match(jobs, /job-table/);
});

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

test("job explorer uses a dense table and focus-safe summary inspector", async () => {
  const jobs = await source("src/components/job-list.tsx");
  const css = await cssBundle();
  assert.match(jobs, /job-explorer/);
  assert.match(jobs, /job-table/);
  assert.match(jobs, /job-inspector/);
  assert.match(jobs, /aria-expanded/);
  assert.match(jobs, /event\.key === "Escape"/);
  assert.match(jobs, /sourceDisplayName/);
  assert.match(jobs, /mobile-job-link/);
  assert.match(css, /\.job-table-row/);
  assert.match(css, /@media\(max-width:767px\)/);
});

test("core data routes use the approved dense archetypes", async () => {
  const overview = await source("src/app/(dashboard)/page.tsx");
  const jobs = await source("src/app/(dashboard)/jobs/page.tsx");
  const analytics = await source("src/app/(dashboard)/analytics/page.tsx");
  assert.match(overview, /route-header/);
  assert.match(overview, /metrics-layout/);
  assert.match(overview, /comparison-list/);
  assert.match(overview, /data-surface/);
  assert.match(jobs, /explorer-toolbar/);
  assert.match(jobs, /data-surface/);
  assert.match(analytics, /comparison-list/);
  assert.match(analytics, /trend-table/);
});

test("operator routes use operations and workflow archetypes", async () => {
  const crawler = await source("src/components/ingestion-console.tsx");
  const sources = await source("src/components/source-recipe-panel.tsx");
  assert.match(crawler, /operations-workspace/);
  assert.match(crawler, /operations-summary/);
  assert.match(crawler, /operations-list/);
  assert.match(sources, /operations-workspace/);
  assert.match(sources, /workflow-panel--form/);
  assert.match(sources, /recipe-preview/);
  assert.match(sources, /visual-mapper/);
  assert.match(sources, /recipe-operations/);
  assert.match(sources, /mapping-viewport/);
  assert.doesNotMatch(crawler, /requestCrawlRun|method:\s*["']POST["']/);
  assert.doesNotMatch(sources, /credential|proxy|bypass/i);
});

test("detail, workflow, policy and auth routes use shared surfaces", async () => {
  const detail = await source("src/app/(dashboard)/jobs/[jobId]/page.tsx");
  const cv = await source("src/components/cv-match-panel.tsx");
  const alerts = await source("src/components/alert-rules-panel.tsx");
  const privacy = await source("src/app/(dashboard)/privacy/page.tsx");
  const login = await source("src/components/login-form.tsx");
  assert.match(detail, /detail-inspector-page/);
  assert.match(detail, /data-surface/);
  assert.match(cv, /workflow-layout/);
  assert.match(cv, /match-results/);
  assert.match(alerts, /workflow-layout/);
  assert.match(alerts, /rule-actions/);
  assert.match(privacy, /policy-reader/);
  assert.match(login, /auth-surface/);
});

test("primary navigation exposes current route and bounded mobile disclosure", async () => {
  const navigation = await source("src/components/primary-navigation.tsx");
  const shell = await source("src/components/app-shell.tsx");

  assert.match(navigation, /usePathname\(\)/);
  assert.match(navigation, /aria-current=\{isActive \? "page" : undefined\}/);
  assert.match(navigation, /aria-expanded=\{open\}/);
  assert.match(navigation, /event\.key === "Escape"/);
  assert.match(navigation, /setOpen\(false\)/);
  assert.match(navigation, /dictionary\.shell\.openNavigation/);
  assert.match(navigation, /dictionary\.shell\.closeNavigation/);
  assert.match(shell, /PrimaryNavigation/);
  assert.doesNotMatch(shell, /routes\.filter/);
});

test("protected CV surface uses semantic redesign classes", async () => {
  const cv = await source("src/components/cv-match-panel.tsx");
  assert.match(cv, /cv-upload-card/);
  assert.match(cv, /score-tile/);
});

test("operator surfaces use semantic redesign classes", async () => {
  const alerts = await source("src/components/alert-rules-panel.tsx");
  const crawler = await source("src/components/ingestion-console.tsx");
  assert.match(alerts, /rule-builder/);
  assert.match(alerts, /rule-card/);
  assert.match(crawler, /health-grid/);
  assert.match(crawler, /run-timeline/);
});

test("redesign preserves CV, crawler and privacy boundaries", async () => {
  const cv = await source("src/components/cv-match-panel.tsx");
  const crawler = await source("src/components/ingestion-console.tsx");
  const recipes = await source("src/components/source-recipe-panel.tsx");
  const privacy = await source("src/app/(dashboard)/privacy/page.tsx");
  assert.match(cv, /MAX_RESUME_BYTES/);
  assert.match(cv, /deleteResume/);
  assert.doesNotMatch(crawler, /requestCrawlRun|method:\s*["']POST["']/);
  assert.match(crawler, /approvalStatus/);
  assert.match(recipes, /PREVIEW_POLL_WINDOW_MS\s*=\s*45_000/);
  assert.match(privacy, /sourceRecipesLocalOnly/);
  assert.match(privacy, /termsWarningOwnerOverride/);
  assert.match(privacy, /accessControlBypassAllowed/);
});
