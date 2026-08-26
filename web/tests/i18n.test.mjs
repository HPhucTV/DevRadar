import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const webRoot = new URL("../", import.meta.url);
const source = (path) => readFile(new URL(path, webRoot), "utf8");

function leafKeys(value, prefix = "") {
  return Object.entries(value).flatMap(([key, child]) => {
    const path = prefix ? `${prefix}.${key}` : key;
    return typeof child === "string" ? [path] : leafKeys(child, path);
  });
}

test("Vietnamese and English dictionaries have exact key parity", async () => {
  const messages = JSON.parse(await source("src/i18n/dictionaries.json"));
  assert.deepEqual(leafKeys(messages.en).sort(), leafKeys(messages.vi).sort());
  assert.equal(messages.vi.locale.vietnamese, "Tiếng Việt");
  assert.equal(messages.en.locale.english, "English");
});

test("locale parser only accepts English and otherwise defaults to Vietnamese", async () => {
  const locale = await source("src/i18n/locale.ts");
  assert.match(locale, /LOCALE_COOKIE\s*=\s*"devradar_locale"/);
  assert.match(locale, /value === "en" \? "en" : "vi"/);
  assert.match(locale, /"vi-VN".*"en-US"/s);
});

test("root layout reads locale cookie and publishes matching html language", async () => {
  const layout = await source("src/app/layout.tsx");
  const server = await source("src/i18n/server.ts");
  const provider = await source("src/i18n/locale-provider.tsx");
  assert.match(server, /await cookies\(\)/);
  assert.match(layout, /<html lang=\{locale\}>/);
  assert.match(layout, /LocaleProvider/);
  assert.match(provider, /createContext/);
  assert.match(provider, /useI18n/);
});

test("language switch is accessible and refreshes the current route", async () => {
  const control = await source("src/components/language-switcher.tsx");
  assert.match(control, /aria-pressed/);
  assert.match(control, /SameSite=Lax/);
  assert.match(control, /Max-Age=31536000/);
  assert.match(control, /router\.refresh\(\)/);
  assert.doesNotMatch(control, /router\.(?:push|replace)\(/);
});

test("domain wire values have localized presentation labels", async () => {
  const messages = JSON.parse(await source("src/i18n/dictionaries.json"));
  for (const value of [
    "parsed", "invalid", "skipped", "created", "updated", "reactivated",
    "language", "framework", "database", "cloud", "messaging", "testing", "ai", "tool", "other",
  ]) {
    assert.equal(typeof messages.vi.status[value], "string", `missing vi.status.${value}`);
    assert.equal(typeof messages.en.status[value], "string", `missing en.status.${value}`);
  }
  for (const field of ["status", "title", "company_name", "description_text", "location_city", "salary_raw", "levels"]) {
    assert.equal(typeof messages.vi.jobDetail.fields[field], "string", `missing vi.jobDetail.fields.${field}`);
    assert.equal(typeof messages.en.jobDetail.fields[field], "string", `missing en.jobDetail.fields.${field}`);
  }
});

test("source route confirmation has complete Vietnamese and English copy", async () => {
  const messages = JSON.parse(await source("src/i18n/dictionaries.json"));
  for (const key of [
    "routeProposalEyebrow",
    "routeProposalTitle",
    "routeProposalBody",
    "routeProposalHosts",
    "routeProposalPaths",
    "confirmRoutes",
    "confirmingRoutes",
    "routesConfirmed",
  ]) {
    assert.equal(typeof messages.vi.sourceRecipes[key], "string", `missing vi.sourceRecipes.${key}`);
    assert.equal(typeof messages.en.sourceRecipes[key], "string", `missing en.sourceRecipes.${key}`);
  }
});

test("source document import has complete Vietnamese and English copy", async () => {
  const messages = JSON.parse(await source("src/i18n/dictionaries.json"));
  for (const key of [
    "documentImportEyebrow",
    "documentImportTitle",
    "documentImportBody",
    "documentImportFile",
    "documentImportHelp",
    "documentImportAction",
    "documentImporting",
    "documentImportComplete",
    "documentImportFileRequired",
    "documentImportFailed",
    "documentImportFound",
    "documentImportNew",
    "documentImportUpdated",
    "documentImportUnchanged",
    "documentImportFiltered",
  ]) {
    assert.equal(typeof messages.vi.sourceRecipes[key], "string", `missing vi.sourceRecipes.${key}`);
    assert.equal(typeof messages.en.sourceRecipes[key], "string", `missing en.sourceRecipes.${key}`);
  }
  assert.match(messages.vi.sourceRecipes.documentImportTitle, /tệp/i);
  assert.match(messages.en.sourceRecipes.documentImportTitle, /file/i);
  for (const code of [
    "document_import_disabled",
    "document_import_recipe_invalid",
    "document_import_acknowledgement_required",
    "document_import_too_large",
    "document_import_multipart_invalid",
    "document_import_type_unsupported",
    "document_import_invalid",
    "document_import_challenge_detected",
    "document_import_no_jobs",
    "document_import_route_blocked",
    "idempotency_key_required",
    "idempotency_key_invalid",
    "idempotency_conflict",
    "document_import_in_progress",
    "document_import_failed",
    "source_document_import_invalid",
  ]) {
    assert.equal(
      typeof messages.vi.sourceRecipes.documentImportErrors[code],
      "string",
      `missing vi.sourceRecipes.documentImportErrors.${code}`,
    );
    assert.equal(
      typeof messages.en.sourceRecipes.documentImportErrors[code],
      "string",
      `missing en.sourceRecipes.documentImportErrors.${code}`,
    );
  }
});

test("job detail and analytics localize enum and date presentation", async () => {
  const detail = await source("src/app/(dashboard)/jobs/[jobId]/page.tsx");
  const analytics = await source("src/app/(dashboard)/analytics/page.tsx");
  assert.match(detail, /statusLabels\[item\.currentSnapshot\.parseStatus\]/);
  assert.match(detail, /statusLabels\[change\.changeType\]/);
  assert.match(detail, /fieldLabels\[change\.fieldName\]/);
  assert.doesNotMatch(detail, /<dd>\{item\.currentSnapshot\.parseStatus\}<\/dd>/);
  assert.match(analytics, /categoryLabels\[skill\.category\]/);
  assert.match(analytics, /formatDate\(bucket\.periodStart/);
  assert.doesNotMatch(analytics, /<strong>\{bucket\.periodStart\}<\/strong>/);
});

const serverSurfaces = [
  "src/app/login/page.tsx",
  "src/app/(dashboard)/page.tsx",
  "src/app/(dashboard)/jobs/page.tsx",
  "src/app/(dashboard)/jobs/[jobId]/page.tsx",
  "src/app/(dashboard)/analytics/page.tsx",
  "src/app/(dashboard)/crawler-health/page.tsx",
  "src/app/(dashboard)/cv-match/page.tsx",
  "src/app/(dashboard)/alerts/page.tsx",
  "src/app/(dashboard)/sources/page.tsx",
  "src/app/(dashboard)/privacy/page.tsx",
];

for (const path of serverSurfaces) {
  test(`${path} reads the server dictionary`, async () => {
    assert.match(await source(path), /getI18n\(\)/);
  });
}

const clientSurfaces = [
  "src/app/(dashboard)/error.tsx",
  "src/components/api-state.tsx",
  "src/components/auth-controls.tsx",
  "src/components/login-form.tsx",
  "src/components/primary-navigation.tsx",
  "src/components/job-list.tsx",
  "src/components/route-placeholder.tsx",
];

for (const path of clientSurfaces) {
  test(`${path} reads the client dictionary`, async () => {
    assert.match(await source(path), /useI18n\(\)/);
  });
}

const interactivePanels = [
  "src/components/ingestion-console.tsx",
  "src/components/cv-match-panel.tsx",
  "src/components/alert-rules-panel.tsx",
  "src/components/source-recipe-panel.tsx",
];

for (const path of interactivePanels) {
  test(`${path} localizes interactive copy and generated dates`, async () => {
    const content = await source(path);
    assert.match(content, /useI18n\(\)/);
    assert.doesNotMatch(content, /toLocale(?:Date)?String\("vi-VN"\)/);
  });

  test(`${path} renders async feedback with the current locale`, async () => {
    const content = await source(path);
    assert.match(content, /type Notice = \(dictionary: Dictionary, locale: Locale\) => string;/);
    assert.match(content, /useState<Notice \| null>\(null\)/);
    assert.match(content, /setNotice\(\(\) =>/);
    assert.match(content, /notice\(dictionary, locale\)/);
  });
}
