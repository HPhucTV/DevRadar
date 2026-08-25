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

test("document import BFF validates and rebuilds one bounded multipart upload", async () => {
  const route = await source(
    "src/app/api/devradar/source-recipes/[recipeId]/document-imports/route.ts",
  );

  assert.match(route, /UUID_PATTERN/);
  assert.match(route, /Array\.from\(incoming\.entries\(\)\)/);
  assert.match(route, /parts\.length !== 1/);
  assert.match(route, /fieldName !== "file"/);
  assert.match(route, /file instanceof File/);
  assert.match(route, /MAX_SOURCE_DOCUMENT_BYTES = 2 \* 1024 \* 1024/);
  assert.match(
    route,
    /MAX_SOURCE_DOCUMENT_REQUEST_BYTES = MAX_SOURCE_DOCUMENT_BYTES \+ 64 \* 1024/,
  );
  assert.match(route, /request\.body\.getReader\(\)/);
  assert.ok(
    route.indexOf("request.body.getReader()") < route.indexOf("boundedRequest.formData()"),
    "the BFF must cap the request stream before parsing multipart data",
  );
  assert.match(route, /file\.size > MAX_SOURCE_DOCUMENT_BYTES/);
  assert.match(route, /new FormData\(\)/);
  assert.match(route, /form\.append\("file", file/);
  assert.match(route, /proxyBackend/);
  assert.doesNotMatch(
    route,
    /headers\.set\(\s*["']content-type|["']content-type["']\s*:/i,
  );
});

test("document import BFF creates or forwards a valid idempotency key", async () => {
  const route = await source(
    "src/app/api/devradar/source-recipes/[recipeId]/document-imports/route.ts",
  );

  assert.match(route, /randomUUID/);
  assert.match(route, /request\.headers\.get\("idempotency-key"\)/);
  assert.match(route, /IDEMPOTENCY_PATTERN/);
  assert.match(route, /"Idempotency-Key": idempotencyKey/);
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

test("typed document import client preserves multipart boundaries and validates the response", async () => {
  const client = await source("src/lib/source-recipes.ts");
  const importStart = client.indexOf("export function importSourceDocument");
  const importBody = client.slice(importStart, client.indexOf("\n}", importStart) + 2);

  assert.match(client, /typeof init\.body === "string"/);
  assert.match(client, /export type SourceRecipeDocumentImport/);
  assert.match(client, /function isDocumentImport/);
  for (const field of [
    "jobsFound",
    "jobsNew",
    "jobsUpdated",
    "jobsUnchanged",
    "itemsFilteredOut",
  ]) {
    assert.match(client, new RegExp(`isNonNegativeInteger\\(value\\.${field}\\)`));
  }
  assert.match(client, /value\.coverage === "incomplete"/);
  assert.match(client, /DOCUMENT_HASH_PREFIX_PATTERN\.test\(value\.documentHashPrefix\)/);
  assert.ok(importStart >= 0);
  assert.match(importBody, /new FormData\(\)/);
  assert.match(importBody, /form\.append\("file", file/);
  assert.doesNotMatch(importBody, /content-type/i);
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

test("source recipe editor offers an accessible local document import fallback", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");
  const termsStart = panel.indexOf("className={`terms-notice");
  const importStart = panel.indexOf('className="document-import-card"');
  const blockedStart = panel.indexOf('selected?.status === "blocked"');
  const importCard = panel.slice(importStart, blockedStart);

  assert.ok(termsStart >= 0 && termsStart < importStart && importStart < blockedStart);
  assert.match(panel, /useState<File \| null>/);
  assert.match(panel, /useState<SourceRecipeDocumentImport \| null>/);
  assert.match(panel, /importSourceDocument/);
  assert.match(importCard, /htmlFor="source-recipe-document"/);
  assert.match(importCard, /accept="\.html,\.htm,\.json,\.csv"/);
  assert.match(importCard, /disabled=\{documentImportDisabled\}/);
  assert.match(panel, /selected\.status === "retired"/);
  assert.match(panel, /selected\.termsAcknowledgementRequired/);
  assert.match(panel, /busy !== null/);
  assert.equal((importCard.match(/button-primary/g) ?? []).length, 1);
  assert.match(importCard, /busy === "document-import"/);
  assert.match(importCard, /aria-live="polite"/);
  assert.match(importCard, /<dl/);
  for (const field of [
    "jobsFound",
    "jobsNew",
    "jobsUpdated",
    "jobsUnchanged",
    "itemsFilteredOut",
  ]) {
    assert.match(importCard, new RegExp(`documentImportResult\\.${field}`));
  }
  assert.match(panel, /formElement\.reset\(\)/);
  assert.match(panel, /setDocumentFile\(null\)/);
  assert.doesNotMatch(panel, /localStorage|FileReader|readAsText|\.text\(\)|dangerouslySetInnerHTML/);
});

test("document import errors use localized safe-code copy", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");
  const importStart = panel.indexOf("async function importDocument");
  const importEnd = panel.indexOf("async function confirmRoutes", importStart);
  const handler = panel.slice(importStart, importEnd);

  assert.match(panel, /function localizeDocumentImportFailure/);
  assert.match(panel, /copy\.documentImportErrors\[error\.code\]/);
  assert.match(panel, /copy\.documentImportFailed/);
  assert.match(handler, /setError\(localizeDocumentImportFailure\(acknowledgement, copy\)\)/);
  assert.match(handler, /setError\(localizeDocumentImportFailure\(result, copy\)\)/);
  assert.doesNotMatch(handler, /setError\(acknowledgement\)/);
  assert.doesNotMatch(handler, /setError\(result\)/);
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

test("terminal preview refresh completes before polling effect cleanup", async () => {
  const panel = await source("src/components/source-recipe-panel.tsx");
  const terminalBranch = panel.indexOf("if (PREVIEW_TERMINAL.has(nextPreview.status))");
  const refreshRecipes = panel.indexOf("const refreshed = await listSourceRecipes();", terminalBranch);
  const clearPoll = panel.indexOf("setPreviewPoll(null);", terminalBranch);

  assert.ok(terminalBranch >= 0);
  assert.ok(refreshRecipes >= 0);
  assert.ok(clearPoll >= 0);
  assert.ok(
    refreshRecipes < clearPoll,
    "clearing previewPoll first cancels the effect and discards the refreshed recipe status",
  );
});
