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
  const preview = await source("src/app/api/devradar/source-recipes/[recipeId]/previews/route.ts");
  const mapping = await source(
    "src/app/api/devradar/source-recipes/[recipeId]/previews/[previewId]/mapping/route.ts",
  );
  const runs = await source("src/app/api/devradar/source-recipes/[recipeId]/crawl-runs/route.ts");
  assert.match(collection, /RECIPE_FIELDS/);
  assert.match(preview, /Object\.keys\(body\)\.length/);
  assert.match(mapping, /MAPPING_FIELDS/);
  assert.match(runs, /Object\.keys\(body\)\.length/);
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
