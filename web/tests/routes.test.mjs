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
  ["crawler-health", "/crawler-health", "implemented", true],
  ["cv-match", "/cv-match", "implemented", true],
  ["alerts", "/alerts", "implemented", true],
  ["source-recipes", "/sources", "implemented", true],
  ["privacy", "/privacy", "implemented", false],
];

test("route manifest owns the current dashboard surface", async () => {
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
  assert.equal(routes.filter(({ showInNav }) => showInNav).length, 7);
});

test("crawler health route is a read-only operator evidence surface", async () => {
  const routes = JSON.parse(await readFile(new URL("src/contracts/routes.json", webRoot), "utf8"));
  const route = routes.find(({ id }) => id === "crawler-health");
  assert.deepEqual(route.apiResources, [
    "GET /api/devradar/sources",
    "GET /api/devradar/crawl-runs",
  ]);
  const page = await readFile(new URL("src/app/(dashboard)/crawler-health/page.tsx", webRoot), "utf8");
  const component = await readFile(new URL("src/components/ingestion-console.tsx", webRoot), "utf8");
  const dictionaries = await readFile(new URL("src/i18n/dictionaries.json", webRoot), "utf8");
  assert.match(page, /IngestionConsole/);
  assert.doesNotMatch(page, /RoutePlaceholder/);
  assert.match(component, /approvalStatus/);
  assert.match(dictionaries, /read.only/i);
  assert.doesNotMatch(component, /allowedHosts|rateLimitPolicy|baseUrl/);
  assert.doesNotMatch(component, /requestCrawlRun|runSource|activeRunId/);
});

test("crawler console does not mutate or poll crawl runs", async () => {
  const component = await readFile(new URL("src/components/ingestion-console.tsx", webRoot), "utf8");
  const client = await readFile(new URL("src/lib/ingestion.ts", webRoot), "utf8");
  assert.doesNotMatch(component + client, /requestCrawlRun|getIngestionRun|method:\s*["']POST["']/);
});

test("sources route owns the complete recipe contract", async () => {
  const routes = JSON.parse(await readFile(manifestUrl, "utf8"));
  const route = routes.find(({ id }) => id === "source-recipes");
  assert.deepEqual(route.apiResources, [
    "GET /api/devradar/source-catalog",
    "GET /api/devradar/source-recipes",
    "POST /api/devradar/source-recipes",
    "PATCH /api/devradar/source-recipes/{recipeId}",
    "DELETE /api/devradar/source-recipes/{recipeId}",
    "POST /api/devradar/source-recipes/{recipeId}/purge",
    "POST /api/devradar/source-recipes/{recipeId}/previews",
    "GET /api/devradar/source-recipes/{recipeId}/previews/{previewId}",
    "POST /api/devradar/source-recipes/{recipeId}/previews/{previewId}/mapping",
    "GET /api/devradar/source-recipes/{recipeId}/crawl-runs",
    "POST /api/devradar/source-recipes/{recipeId}/crawl-runs",
    "POST /api/devradar/source-recipes/{recipeId}/document-imports",
  ]);
});

test("jobs route forwards and preserves only a bounded source filter", async () => {
  const page = await readFile(new URL("src/app/(dashboard)/jobs/page.tsx", webRoot), "utf8");
  const api = await readFile(new URL("src/lib/api.ts", webRoot), "utf8");

  assert.match(page, /parseJobSourceId\(params\.sourceId\)/);
  assert.match(page, /listJobs\(\{[^}]*sourceId/s);
  assert.match(page, /type="hidden" name="sourceId" value=\{sourceId\}/);
  assert.match(api, /sourceId\?: string/);
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

test("explicit local no-login mode hides session controls and redirects login", async () => {
  const shell = await readFile(new URL("src/components/app-shell.tsx", webRoot), "utf8");
  const controls = await readFile(new URL("src/components/auth-controls.tsx", webRoot), "utf8");
  const login = await readFile(new URL("src/app/login/page.tsx", webRoot), "utf8");

  assert.match(shell, /localNoLoginEnabled/);
  assert.match(controls, /localNoLoginEnabled/);
  assert.match(login, /redirect\("\/"\)/);
  assert.match(login, /localNoLoginEnabled/);
});

test("BFF has bounded rate, timeout and security-header policy", async () => {
  const proxy = await readFile(new URL("src/lib/backend-proxy.ts", webRoot), "utf8");
  const nextConfig = await readFile(new URL("next.config.mjs", webRoot), "utf8");

  assert.match(proxy, /AbortSignal\.timeout/);
  assert.match(proxy, /bff-rate-limit/);
  assert.match(proxy, /MAX_PROXY_BODY_BYTES/);
  assert.match(nextConfig, /X-Content-Type-Options/);
  assert.match(nextConfig, /Content-Security-Policy/);
  assert.match(nextConfig, /Referrer-Policy/);
});

test("privacy route exposes truthful retention, AI and source policy", async () => {
  const routes = JSON.parse(await readFile(manifestUrl, "utf8"));
  const route = routes.find((candidate) => candidate.id === "privacy");
  const page = await readFile(new URL(route.pageFile, webRoot), "utf8");
  const bff = await readFile(new URL("src/app/api/devradar/privacy/route.ts", webRoot), "utf8");
  const shell = await readFile(new URL("src/components/app-shell.tsx", webRoot), "utf8");
  const navigation = await readFile(new URL("src/components/primary-navigation.tsx", webRoot), "utf8");
  const dictionaries = await readFile(new URL("src/i18n/dictionaries.json", webRoot), "utf8");
  assert.match(page, /resumeProfileTtlHours/);
  assert.match(page, /sourceRecipesLocalOnly/);
  assert.doesNotMatch(page, /termsWarningOwnerOverride|termsOverride/);
  assert.match(page, /accessControlBypassAllowed/);
  assert.match(page, /externalAllowed|externalBlocked/);
  assert.doesNotMatch(page, /permissionRequiredSourceKeys|sourceAllowlistOnly/);
  assert.match(dictionaries, /external LLM/i);
  assert.match(page, /ApiErrorState/);
  assert.match(bff, /proxyBackend/);
  assert.match(shell + navigation, /privacy/);
});
