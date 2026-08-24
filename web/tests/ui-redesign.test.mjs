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

test("document does not force horizontal overflow at a 320px viewport", async () => {
  const css = await source("src/app/globals.css");
  assert.doesNotMatch(css, /html\{[^}]*min-width:\s*320px/);
});

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

test("shared shell and route surfaces use redesign primitives", async () => {
  const shell = await source("src/components/app-shell.tsx");
  const overview = await source("src/app/(dashboard)/page.tsx");
  const jobs = await source("src/components/job-list.tsx");
  assert.match(shell, /brand-mark/);
  assert.match(shell, /PrimaryNavigation/);
  assert.match(overview, /dashboard-grid/);
  assert.match(jobs, /job-card/);
});

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
  const privacy = await source("src/app/(dashboard)/privacy/page.tsx");
  assert.match(cv, /MAX_RESUME_BYTES/);
  assert.match(cv, /deleteResume/);
  assert.match(crawler, /POLL_WINDOW_MS\s*=\s*30_000/);
  assert.match(crawler, /approvalStatus/);
  assert.match(privacy, /GeoComply|Lever/);
});
