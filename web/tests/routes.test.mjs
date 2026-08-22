import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
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
