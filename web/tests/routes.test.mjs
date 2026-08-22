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
  ["cv-match", "/cv-match", "implemented", true],
  ["alerts", "/alerts", "implemented", true],
];

test("route manifest owns the current V5 surface", async () => {
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
  assert.deepEqual(routes.find(({ id }) => id === "cv-match").apiResources, [
    "POST /api/v1/resume-profiles",
    "POST /api/v1/resume-profiles/{profileId}/matches",
    "GET /api/v1/resume-profiles/{profileId}/matches",
    "DELETE /api/v1/resume-profiles/{profileId}",
  ]);
  assert.equal(routes.filter(({ showInNav }) => showInNav).length, 6);
});

test("cv match route exposes only protected local matching resources", async () => {
  const source = await readFile(
    new URL("src/app/(dashboard)/cv-match/page.tsx", webRoot),
    "utf8",
  );
  const routes = JSON.parse(
    await readFile(new URL("src/contracts/routes.json", webRoot), "utf8"),
  );
  const route = routes.find((candidate) => candidate.id === "cv-match");

  assert.deepEqual(route.apiResources, [
    "POST /api/v1/resume-profiles",
    "POST /api/v1/resume-profiles/{profileId}/matches",
    "GET /api/v1/resume-profiles/{profileId}/matches",
    "DELETE /api/v1/resume-profiles/{profileId}",
  ]);
  assert.match(source, /CvMatchPanel/);
  assert.doesNotMatch(source, /RoutePlaceholder/);
});

test("cv match client uses the authenticated session without browser token storage", async () => {
  const source = await readFile(new URL("src/components/cv-match-panel.tsx", webRoot), "utf8");
  const clientApi = await readFile(new URL("src/lib/cv-match.ts", webRoot), "utf8");
  const sessionRequest = await readFile(new URL("src/lib/session-request.ts", webRoot), "utf8");

  assert.doesNotMatch(clientApi, /X-DevRadar-Owner/);
  assert.match(sessionRequest, /credentials:\s*["']include["']/);
  assert.match(sessionRequest, /X-DevRadar-CSRF/);
  assert.match(clientApi, /FormData/);
  assert.doesNotMatch(source + clientApi + sessionRequest, /localStorage/);
  assert.doesNotMatch(source, /Owner token/);
  assert.match(source, /MAX_RESUME_BYTES/);
});

test("cv match proxy preserves no-content delete responses", async () => {
  const source = await readFile(new URL("src/lib/backend-proxy.ts", webRoot), "utf8");

  assert.match(source, /response\.status === 204/);
  assert.match(source, /\? null/);
  assert.match(source, /cookie/);
  assert.match(source, /x-devradar-csrf/i);
});

test("alert route exposes only protected rule and dispatch resources", async () => {
  const routes = JSON.parse(await readFile(new URL("src/contracts/routes.json", webRoot), "utf8"));
  const route = routes.find(({ id }) => id === "alerts");
  assert.deepEqual(route.apiResources, [
    "GET /api/v1/alert-rules",
    "POST /api/v1/alert-rules",
    "PATCH /api/v1/alert-rules/{ruleId}",
    "DELETE /api/v1/alert-rules/{ruleId}",
    "POST /api/v1/alert-rules/{ruleId}/dispatch",
  ]);
  const source = await readFile(new URL("src/components/alert-rules-panel.tsx", webRoot), "utf8");
  const clientApi = await readFile(new URL("src/lib/alert-rules.ts", webRoot), "utf8");
  const sessionRequest = await readFile(new URL("src/lib/session-request.ts", webRoot), "utf8");
  assert.doesNotMatch(source, /Owner token/);
  assert.doesNotMatch(clientApi, /X-DevRadar-Owner/);
  assert.match(sessionRequest, /X-DevRadar-CSRF/);
  assert.doesNotMatch(source + clientApi + sessionRequest, /localStorage\.|webhookUrl|DISCORD_WEBHOOK_URL/);
});

test("auth routes and login page are present", async () => {
  await access(new URL("src/app/api/devradar/auth/login/route.ts", webRoot));
  await access(new URL("src/app/api/devradar/auth/logout/route.ts", webRoot));
  await access(new URL("src/app/api/devradar/auth/me/route.ts", webRoot));
  await access(new URL("src/app/login/page.tsx", webRoot));
  const proxy = await readFile(new URL("src/lib/backend-proxy.ts", webRoot), "utf8");
  assert.match(proxy, /set-cookie/);
  assert.match(proxy, /headers\.append\(["']set-cookie["']/);
  assert.doesNotMatch(proxy, /x-devradar-owner/i);
});
