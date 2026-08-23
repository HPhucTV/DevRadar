import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, webRoot), "utf8");

test("custom source route and panel expose the protected local workflow", async () => {
  const routes = JSON.parse(await source("src/contracts/routes.json"));
  const route = routes.find((candidate) => candidate.id === "custom-sources");
  assert.ok(route);
  assert.equal(route.path, "/sources");
  assert.equal(route.showInNav, true);
  await access(new URL(route.pageFile, webRoot));

  const panel = await source("src/components/custom-source-panel.tsx");
  assert.match(panel, /Test crawl/);
  assert.match(panel, /permission|authorized|local/i);
  assert.match(panel, /daily_at|interval_minutes|timezone/);
  assert.match(panel, /preview|preview_ready/i);
  assert.match(panel, /blocked|permission_required/i);
  assert.match(panel, /finalUrl|redirectChain|coverageStatus|warnings/);
  assert.match(panel, /candidate\.provenance/);
  assert.match(panel, /custom-byte-budget/);
  for (const field of ["salary", "description", "postedAt"]) {
    assert.match(panel, new RegExp(`\\["${field}",`));
  }
  assert.doesNotMatch(panel, /localStorage|document\.cookie|bypass|captcha.?solve/i);
  assert.doesNotMatch(await source("src/app/api/devradar/custom-sources/route.ts"), /page_budget/);
});

test("custom source client preserves bounded resource paths and safe contracts", async () => {
  const client = await source("src/lib/custom-sources.ts");
  assert.match(client, /\/api\/devradar\/custom-sources/);
  assert.match(client, /X-DevRadar-CSRF|sessionFetch/);
  assert.match(client, /Idempotency-Key/);
  assert.match(client, /Array\.isArray\(value\.provenance\)/);
  assert.match(client, /fieldName.*sourcePath.*method/s);
  assert.doesNotMatch(client, /proxyUrl|cookie|authorization|outboundUrl|bypass/i);
});

test("custom source BFF routes forward session and CSRF without arbitrary outbound fields", async () => {
  const collection = await source("src/app/api/devradar/custom-sources/route.ts");
  const profile = await source("src/app/api/devradar/custom-sources/[profileId]/route.ts");
  const preview = await source("src/app/api/devradar/custom-sources/[profileId]/preview/route.ts");
  const runs = await source("src/app/api/devradar/custom-sources/[profileId]/crawl-runs/route.ts");
  const bff = `${collection}\n${profile}\n${preview}\n${runs}`;
  assert.match(bff, /proxyBackend/);
  assert.match(bff, /X-DevRadar-CSRF|proxyBackend/);
  assert.match(bff, /custom-sources/);
  assert.doesNotMatch(bff, /proxyUrl|cookies|authorization|outboundUrl|bypass|captcha.?solve/i);
});

test("shared BFF marks serialized mutation bodies as JSON", async () => {
  const proxy = await source("src/lib/backend-proxy.ts");
  assert.match(proxy, /typeof init\.body === "string"/);
  assert.match(proxy, /content-type.*application\/json/i);
});

test("custom source panel keeps enabling behind a successful preview", async () => {
  const panel = await source("src/components/custom-source-panel.tsx");
  assert.match(panel, /previewReady|preview_ready|lastPreviewAt/);
  assert.match(panel, /disabled=.*preview|preview.*disabled|canEnable/i);
  assert.match(panel, /pause|retire/i);
  assert.match(panel, /crawl-runs|history/i);
});
