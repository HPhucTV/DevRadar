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
  "src/components/job-list.tsx",
];

for (const path of serverSurfaces) {
  test(`${path} reads the server dictionary`, async () => {
    assert.match(await source(path), /getI18n\(\)/);
  });
}

const clientSurfaces = [
  "src/app/(dashboard)/error.tsx",
  "src/app/(dashboard)/loading.tsx",
  "src/components/api-state.tsx",
  "src/components/auth-controls.tsx",
  "src/components/login-form.tsx",
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
  "src/components/custom-source-panel.tsx",
];

for (const path of interactivePanels) {
  test(`${path} localizes interactive copy and generated dates`, async () => {
    const content = await source(path);
    assert.match(content, /useI18n\(\)/);
    assert.doesNotMatch(content, /toLocale(?:Date)?String\("vi-VN"\)/);
  });
}
