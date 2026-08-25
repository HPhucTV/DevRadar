import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, webRoot), "utf8");

test("source recipe BFF surface exists and uses bounded backend paths", async () => {
  const files = [
    "src/app/api/devradar/source-catalog/route.ts",
    "src/app/api/devradar/source-recipes/route.ts",
    "src/app/api/devradar/source-recipes/[recipeId]/route.ts",
    "src/app/api/devradar/source-recipes/[recipeId]/previews/route.ts",
    "src/app/api/devradar/source-recipes/[recipeId]/previews/[previewId]/route.ts",
    "src/app/api/devradar/source-recipes/[recipeId]/previews/[previewId]/mapping/route.ts",
    "src/app/api/devradar/source-recipes/[recipeId]/crawl-runs/route.ts",
  ];
  for (const file of files) await access(new URL(file, webRoot));
  const bff = (await Promise.all(files.map(source))).join("\n");
  assert.match(bff, /proxyBackend/);
  assert.match(bff, /UUID_PATTERN/);
  assert.match(bff, /Idempotency-Key/);
  assert.match(bff, /Object\.keys/);
  assert.doesNotMatch(bff, /proxyUrl|authorization|outboundUrl|bypass|captcha.?solve/i);
});

test("source recipe BFF rejects arbitrary fetch and code fields", async () => {
  const collection = await source("src/app/api/devradar/source-recipes/route.ts");
  const detail = await source("src/app/api/devradar/source-recipes/[recipeId]/route.ts");
  const preview = await source("src/app/api/devradar/source-recipes/[recipeId]/previews/route.ts");
  const mapping = await source(
    "src/app/api/devradar/source-recipes/[recipeId]/previews/[previewId]/mapping/route.ts",
  );
  const runs = await source("src/app/api/devradar/source-recipes/[recipeId]/crawl-runs/route.ts");
  assert.match(collection, /RECIPE_FIELDS/);
  assert.doesNotMatch(collection, /"allowedHosts"|"allowedPathPrefixes"/);
  assert.match(detail, /"allowedHosts"/);
  assert.match(detail, /"allowedPathPrefixes"/);
  assert.match(preview, /Object\.keys\(body\)\.length/);
  assert.match(mapping, /MAPPING_FIELDS/);
  assert.match(runs, /Object\.keys\(body\)\.length/);
});

test("generic crawl-run BFF is read-only after the recipe hard cut", async () => {
  const runs = await source("src/app/api/devradar/crawl-runs/route.ts");

  assert.match(runs, /export async function GET/);
  assert.doesNotMatch(runs, /export async function POST/);
  assert.doesNotMatch(runs, /sourceId|Idempotency-Key/);
});

test("typed source recipe client validates screenshot bounds and stores no browser secrets", async () => {
  const client = await source("src/lib/source-recipes.ts");
  const proxy = await source("src/lib/backend-proxy.ts");
  assert.match(client, /MAX_SCREENSHOT_DATA_URL_LENGTH/);
  assert.match(client, /data:image/);
  assert.match(client, /webp\|png/);
  assert.match(client, /sessionFetch/);
  assert.match(client, /Idempotency-Key/);
  assert.match(proxy, /MAX_PROXY_RESPONSE_BYTES = 3 \* 1024 \* 1024/);
  assert.doesNotMatch(client, /localStorage|document\.cookie|selector|rawHtml|bypass/i);
});

test("sources page exposes the no-code recipe workflow", async () => {
  const page = await source("src/app/(dashboard)/sources/page.tsx");
  const panel = await source("src/components/source-recipe-panel.tsx");

  assert.match(page, /SourceRecipePanel/);
  assert.match(panel, /id="source-recipe-listing-url"/);
  assert.match(panel, /type="url"/);
  assert.match(panel, /SENIORITY_OPTIONS/);
  assert.match(panel, /toggleSeniority/);
  assert.match(panel, /value === "all"/);
  assert.match(panel, /termsNoticeVersion/);
  assert.match(panel, /acknowledgedNoticeVersion/);
  assert.match(panel, /termsEvidenceUrl/);
  assert.match(panel, /requestSourcePreview/);
  assert.match(panel, /getSourcePreview/);
  assert.match(panel, /PREVIEW_POLL_WINDOW_MS/);
  assert.match(panel, /preview\.candidates\.slice\(0, 5\)/);
});

test("visual mapper uses safe opaque controls for keyboard and pointer input", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");

  assert.match(panel, /screenshotDataUrl/);
  assert.match(panel, /mapping-overlay/);
  assert.match(panel, /type="button"/);
  assert.match(panel, /selectMappingElement/);
  assert.match(panel, /element\.elementId/);
  assert.match(panel, /locationElementId:\s*null/);
  assert.match(panel, /paginationElementId:\s*null/);
  assert.match(panel, /saveSourceMapping/);
  assert.doesNotMatch(panel, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(panel, /selector|rawHtml|innerHTML/i);
});

test("recipe operations are bounded to fixed schedules and safe states", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");
  const client = await source("src/lib/source-recipes.ts");

  for (const value of ["manual", "every_6_hours", "daily", "weekly"]) {
    assert.match(panel, new RegExp(`value=["']${value}["']`));
  }
  assert.match(panel, /requestSourceCrawl/);
  assert.match(panel, /listSourceCrawls/);
  assert.match(panel, /"enabled"/);
  assert.match(panel, /"paused"/);
  assert.match(panel, /retireSourceRecipe/);
  assert.match(panel, /blockReason/);
  assert.match(panel, /cooldownUntil/);
  assert.doesNotMatch(panel + client, /credential|cookie|proxy|captcha.?solve|bypass|cronExpression|cron-expression/i);
});

test("preview route proposals require one exact confirmation before enable", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");
  const client = await source("src/lib/source-recipes.ts");

  assert.match(client, /allowedHosts:\s*string\[\]/);
  assert.match(client, /allowedPathPrefixes:\s*string\[\]/);
  assert.match(client, /proposedPathPrefixes:\s*string\[\]/);
  assert.match(client, /Array\.isArray\(value\.proposedPathPrefixes\)/);
  assert.match(client, /export function confirmPreviewRoutes/);
  assert.match(panel, /const hasRouteProposal/);
  assert.match(panel, /async function confirmRoutes/);
  assert.match(panel, /selected\.allowedHosts.*preview\.proposedHosts/s);
  assert.match(panel, /selected\.allowedPathPrefixes.*preview\.proposedPathPrefixes/s);
  assert.match(panel, /queuePreviewFor\(patched\.value\.data\)/);
  assert.match(panel, /route-proposal-card/);
  assert.match(panel, /disabled=\{busy !== null \|\| !canEnable \|\| hasRouteProposal\}/);
  assert.doesNotMatch(panel, /name=["']allowedHosts|name=["']allowedPathPrefixes/);
});
