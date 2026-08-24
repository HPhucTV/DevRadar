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
