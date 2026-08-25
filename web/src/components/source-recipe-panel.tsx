"use client";

import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type FormEvent,
  type SyntheticEvent,
} from "react";
import { ApiErrorState, EmptyState } from "@/components/api-state";
import type { Dictionary } from "@/i18n/dictionaries";
import { useI18n } from "@/i18n/locale-provider";
import { formatDate, formatNumber, formatPercent, interpolate, type Locale } from "@/i18n/locale";
import type { ApiFailure } from "@/lib/api";
import {
  confirmPreviewRoutes,
  createSourceRecipe,
  getSourceCatalog,
  getSourcePreview,
  importSourceDocument,
  listSourceCrawls,
  listSourceRecipes,
  requestSourceCrawl,
  requestSourcePreview,
  retireSourceRecipe,
  saveSourceMapping,
  updateSourceRecipe,
  type PreviewElement,
  type SourceCatalogEntry,
  type SourceRecipe,
  type SourceRecipeCrawlRun,
  type SourceRecipeDocumentImport,
  type SourceRecipeInput,
  type SourceRecipeMappingInput,
  type SourceRecipePreview,
} from "@/lib/source-recipes";

export const PREVIEW_POLL_INTERVAL_MS = 1_500;
export const PREVIEW_POLL_WINDOW_MS = 45_000;

const SENIORITY_OPTIONS = ["all", "intern", "fresher", "junior", "mid", "senior", "lead", "manager"] as const;
const PREVIEW_TERMINAL = new Set(["succeeded", "failed"]);
const MAPPING_STEPS = [
  "cardElementId",
  "titleElementId",
  "companyElementId",
  "locationElementId",
  "jobUrlElementId",
  "paginationElementId",
] as const;

type MappingField = (typeof MAPPING_STEPS)[number];
type Notice = (dictionary: Dictionary, locale: Locale) => string;
type FormState = SourceRecipeInput;
type SourceRecipeCopy = Dictionary["sourceRecipes"] & {
  documentImportErrors: Record<string, string>;
};

const DEFAULT_FORM: FormState = {
  name: "",
  listingUrl: "",
  seniorityFilter: ["all"],
  scheduleKind: "manual",
  scheduleLocalTime: null,
  scheduleWeekday: null,
  timezone: "Asia/Ho_Chi_Minh",
};

const DEFAULT_MAPPING: SourceRecipeMappingInput = {
  cardElementId: "",
  titleElementId: "",
  companyElementId: "",
  locationElementId: null,
  jobUrlElementId: "",
  paginationElementId: null,
};

function failure(message: string): ApiFailure {
  return { kind: "error", status: 422, code: "source_recipe_invalid", message };
}

function localizeDocumentImportFailure(
  error: ApiFailure,
  copy: SourceRecipeCopy,
): ApiFailure {
  return {
    ...error,
    message: copy.documentImportErrors[error.code] ?? copy.documentImportFailed,
  };
}

function toForm(recipe: SourceRecipe): FormState {
  return {
    name: recipe.name,
    listingUrl: recipe.listingUrl,
    seniorityFilter: recipe.seniorityFilter,
    scheduleKind: recipe.scheduleKind,
    scheduleLocalTime: recipe.scheduleLocalTime,
    scheduleWeekday: recipe.scheduleWeekday,
    timezone: recipe.timezone,
  };
}

function candidateKey(candidate: SourceRecipePreview["candidates"][number], index: number): string {
  return `${candidate.externalId}:${index}`;
}

function mappingButtonStyle(
  element: PreviewElement,
  imageSize: { width: number; height: number },
): CSSProperties {
  const x = Number(element.bounds.x ?? 0);
  const y = Number(element.bounds.y ?? 0);
  const width = Number(element.bounds.width ?? 44);
  const height = Number(element.bounds.height ?? 44);
  return {
    left: `${Math.max(0, (x / imageSize.width) * 100)}%`,
    top: `${Math.max(0, (y / imageSize.height) * 100)}%`,
    width: `${Math.max(0, (width / imageSize.width) * 100)}%`,
    height: `${Math.max(0, (height / imageSize.height) * 100)}%`,
  };
}

export function SourceRecipePanel() {
  const { locale, dictionary } = useI18n();
  const copy = dictionary.sourceRecipes;
  const statusLabels = dictionary.status as Record<string, string>;
  const [recipes, setRecipes] = useState<SourceRecipe[]>([]);
  const [catalog, setCatalog] = useState<SourceCatalogEntry[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [acknowledged, setAcknowledged] = useState(false);
  const [preview, setPreview] = useState<SourceRecipePreview | null>(null);
  const [previewPoll, setPreviewPoll] = useState<{ recipeId: string; previewId: string; startedAt: number } | null>(null);
  const [runs, setRuns] = useState<SourceRecipeCrawlRun[]>([]);
  const [documentFile, setDocumentFile] = useState<File | null>(null);
  const [documentImportResult, setDocumentImportResult] =
    useState<SourceRecipeDocumentImport | null>(null);
  const [mapping, setMapping] = useState<SourceRecipeMappingInput>(DEFAULT_MAPPING);
  const [mappingStep, setMappingStep] = useState(0);
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState<string | null>("loading");

  const selected = useMemo(
    () => recipes.find((recipe) => recipe.id === selectedId) ?? null,
    [recipes, selectedId],
  );
  const currentMappingField = MAPPING_STEPS[mappingStep] ?? null;
  const hasRouteProposal = Boolean(
    preview && (preview.proposedHosts.length > 0 || preview.proposedPathPrefixes.length > 0),
  );
  const canEnable = selected?.status === "preview_ready" || selected?.status === "paused";
  const canCrawl = selected?.status === "enabled";
  const documentImportDisabled =
    !selected ||
    selected.status === "retired" ||
    (selected.termsAcknowledgementRequired && !selected.termsAcknowledged && !acknowledged) ||
    busy !== null;

  useEffect(() => {
    let active = true;
    void Promise.all([listSourceRecipes(), getSourceCatalog()]).then(([recipeResult, catalogResult]) => {
      if (!active) return;
      if (recipeResult.kind === "success") setRecipes(recipeResult.value.data);
      else setError(recipeResult);
      if (catalogResult.kind === "success") setCatalog(catalogResult.value.data.entries);
      else if (recipeResult.kind === "success") setError(catalogResult);
      setBusy(null);
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!previewPoll) return;
    let active = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      if (!previewPoll) return;
      const result = await getSourcePreview(previewPoll.recipeId, previewPoll.previewId);
      if (!active) return;
      if (result.kind === "error") {
        setError(result);
        setPreviewPoll(null);
        setBusy(null);
        return;
      }
      const nextPreview = result.value.data;
      setPreview(nextPreview);
      if (PREVIEW_TERMINAL.has(nextPreview.status)) {
        const refreshed = await listSourceRecipes();
        if (!active) return;
        if (refreshed.kind === "success") setRecipes(refreshed.value.data);
        setPreviewPoll(null);
        setBusy(null);
        setNotice(() => (messages: Dictionary) =>
          nextPreview.status === "succeeded"
            ? messages.sourceRecipes.previewReady
            : nextPreview.elements.length
              ? messages.sourceRecipes.mappingRequired
              : messages.sourceRecipes.previewStopped,
        );
        return;
      }
      if (Date.now() - previewPoll.startedAt >= PREVIEW_POLL_WINDOW_MS) {
        setPreviewPoll(null);
        setBusy(null);
        setNotice(() => (messages: Dictionary) => messages.sourceRecipes.previewPending);
        return;
      }
      timeout = setTimeout(() => void poll(), PREVIEW_POLL_INTERVAL_MS);
    }

    void poll();
    return () => {
      active = false;
      if (timeout) clearTimeout(timeout);
    };
  }, [previewPoll]);

  function chooseRecipe(recipe: SourceRecipe) {
    setSelectedId(recipe.id);
    setForm(toForm(recipe));
    setAcknowledged(recipe.termsAcknowledged);
    setPreview(null);
    setRuns([]);
    setDocumentFile(null);
    setDocumentImportResult(null);
    setMapping(DEFAULT_MAPPING);
    setMappingStep(0);
    setError(null);
    setNotice(null);
  }

  function resetEditor() {
    setSelectedId(null);
    setForm(DEFAULT_FORM);
    setAcknowledged(false);
    setPreview(null);
    setRuns([]);
    setDocumentFile(null);
    setDocumentImportResult(null);
    setMapping(DEFAULT_MAPPING);
    setMappingStep(0);
    setError(null);
    setNotice(null);
  }

  function chooseCatalogEntry(entry: SourceCatalogEntry) {
    setForm((current) => ({
      ...current,
      name: entry.name,
      listingUrl: `${entry.origin}${entry.listingHint}`,
    }));
  }

  function toggleSeniority(value: string) {
    setForm((current) => {
      if (value === "all") return { ...current, seniorityFilter: ["all"] };
      const withoutAll = current.seniorityFilter.filter((item) => item !== "all");
      const next = withoutAll.includes(value)
        ? withoutAll.filter((item) => item !== value)
        : [...withoutAll, value];
      return { ...current, seniorityFilter: next.length ? next : ["all"] };
    });
  }

  function changeSchedule(value: FormState["scheduleKind"]) {
    setForm((current) => ({
      ...current,
      scheduleKind: value,
      scheduleLocalTime: value === "daily" || value === "weekly" ? current.scheduleLocalTime ?? "09:00" : null,
      scheduleWeekday: value === "weekly" ? current.scheduleWeekday ?? 0 : null,
    }));
  }

  async function saveRecipe(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim() || !form.listingUrl.trim()) {
      setError(failure(copy.validation));
      return;
    }
    setBusy("save");
    setError(null);
    setNotice(null);
    const result = selected
      ? await updateSourceRecipe(selected.id, {
          name: form.name,
          seniorityFilter: form.seniorityFilter,
          scheduleKind: form.scheduleKind,
          scheduleLocalTime: form.scheduleLocalTime,
          scheduleWeekday: form.scheduleWeekday,
          timezone: form.timezone,
        })
      : await createSourceRecipe(form);
    if (result.kind === "error") setError(result);
    else {
      const saved = result.value.data;
      setRecipes((current) =>
        selected
          ? current.map((recipe) => (recipe.id === saved.id ? saved : recipe))
          : [saved, ...current],
      );
      setSelectedId(saved.id);
      setForm(toForm(saved));
      setAcknowledged(saved.termsAcknowledged);
      setPreview(null);
      setNotice(() => (messages: Dictionary) => messages.sourceRecipes.saved);
    }
    setBusy(null);
  }

  async function queuePreviewFor(recipe: SourceRecipe): Promise<boolean> {
    const result = await requestSourcePreview(recipe.id);
    if (result.kind === "error") {
      setError(result);
      setBusy(null);
      return false;
    }
    setPreview(result.value.data);
    setPreviewPoll({ recipeId: recipe.id, previewId: result.value.data.id, startedAt: Date.now() });
    setNotice(() => (messages: Dictionary) => messages.sourceRecipes.previewQueued);
    return true;
  }

  async function queuePreview() {
    if (!selected) return;
    setBusy("preview");
    setError(null);
    setNotice(null);
    let recipe = selected;
    if (recipe.termsAcknowledgementRequired && !recipe.termsAcknowledged) {
      if (!acknowledged) {
        setError(failure(copy.acknowledgementRequired));
        setBusy(null);
        return;
      }
      const ackResult = await updateSourceRecipe(recipe.id, {
        acknowledgedNoticeVersion: recipe.termsNoticeVersion,
      });
      if (ackResult.kind === "error") {
        setError(ackResult);
        setBusy(null);
        return;
      }
      recipe = ackResult.value.data;
      setRecipes((current) => current.map((item) => (item.id === recipe.id ? recipe : item)));
    }
    await queuePreviewFor(recipe);
  }

  async function importDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || documentImportDisabled) return;
    if (!documentFile) {
      setError(failure(copy.documentImportFileRequired));
      return;
    }

    const formElement = event.currentTarget;
    setBusy("document-import");
    setError(null);
    setNotice(null);
    setDocumentImportResult(null);
    let recipe = selected;

    if (recipe.termsAcknowledgementRequired && !recipe.termsAcknowledged) {
      const acknowledgement = await updateSourceRecipe(recipe.id, {
        acknowledgedNoticeVersion: recipe.termsNoticeVersion,
      });
      if (acknowledgement.kind === "error") {
        setError(localizeDocumentImportFailure(acknowledgement, copy));
        setBusy(null);
        return;
      }
      recipe = acknowledgement.value.data;
      setRecipes((current) =>
        current.map((item) => (item.id === recipe.id ? recipe : item)),
      );
      setAcknowledged(recipe.termsAcknowledged);
    }

    const result = await importSourceDocument(recipe.id, documentFile);
    if (result.kind === "error") {
      setError(localizeDocumentImportFailure(result, copy));
    } else {
      setDocumentImportResult(result.value.data);
      setDocumentFile(null);
      formElement.reset();
    }
    setBusy(null);
  }

  async function confirmRoutes() {
    if (!selected || !preview || !hasRouteProposal) return;
    setBusy("confirm-routes");
    setError(null);
    setNotice(null);
    const allowedHosts = [...new Set([...selected.allowedHosts, ...preview.proposedHosts])];
    const allowedPathPrefixes = [
      ...new Set([...selected.allowedPathPrefixes, ...preview.proposedPathPrefixes]),
    ];
    const patched = await confirmPreviewRoutes(
      selected.id,
      allowedHosts,
      allowedPathPrefixes,
    );
    if (patched.kind === "error") {
      setError(patched);
      setBusy(null);
      return;
    }
    const recipe = patched.value.data;
    setRecipes((current) => current.map((item) => (item.id === recipe.id ? recipe : item)));
    setForm(toForm(recipe));
    setPreview(null);
    setMapping(DEFAULT_MAPPING);
    setMappingStep(0);
    setBusy("preview");
    if (await queuePreviewFor(patched.value.data)) {
      setNotice(() => (messages: Dictionary) => messages.sourceRecipes.routesConfirmed);
    }
  }

  function selectMappingElement(elementId: string) {
    if (!currentMappingField) return;
    setMapping((current) => ({ ...current, [currentMappingField]: elementId }));
    setMappingStep((current) => Math.min(current + 1, MAPPING_STEPS.length - 1));
  }

  function markOptionalAbsent() {
    if (currentMappingField === "locationElementId") {
      setMapping((current) => ({ ...current, locationElementId: null }));
      setMappingStep((current) => current + 1);
    } else if (currentMappingField === "paginationElementId") {
      setMapping((current) => ({ ...current, paginationElementId: null }));
    }
  }

  async function submitMapping() {
    if (!selected || !preview) return;
    if (!mapping.cardElementId || !mapping.titleElementId || !mapping.companyElementId || !mapping.jobUrlElementId) {
      setError(failure(copy.mappingIncomplete));
      return;
    }
    setBusy("mapping");
    setError(null);
    const result = await saveSourceMapping(selected.id, preview.id, mapping);
    if (result.kind === "error") {
      setError(result);
      setBusy(null);
      return;
    }
    setPreview(result.value.data);
    setPreviewPoll({ recipeId: selected.id, previewId: result.value.data.id, startedAt: Date.now() });
    setNotice(() => (messages: Dictionary) => messages.sourceRecipes.mappingSaved);
  }

  async function changeStatus(status: "enabled" | "paused") {
    if (!selected) return;
    setBusy(status);
    setError(null);
    const result = await updateSourceRecipe(selected.id, { status });
    if (result.kind === "error") setError(result);
    else {
      setRecipes((current) => current.map((item) => (item.id === result.value.data.id ? result.value.data : item)));
      setNotice(() => (messages: Dictionary) =>
        status === "enabled" ? messages.sourceRecipes.enabled : messages.sourceRecipes.paused,
      );
    }
    setBusy(null);
  }

  async function crawlNow() {
    if (!selected || !canCrawl) return;
    setBusy("crawl");
    setError(null);
    const result = await requestSourceCrawl(selected.id);
    if (result.kind === "error") setError(result);
    else {
      setNotice(() => (messages: Dictionary) =>
        interpolate(messages.sourceRecipes.crawlQueued, {
          status: (messages.status as Record<string, string>)[result.value.data.status] ?? result.value.data.status,
        }),
      );
      await loadHistory(selected.id);
    }
    setBusy(null);
  }

  async function loadHistory(recipeId: string) {
    const result = await listSourceCrawls(recipeId);
    if (result.kind === "error") setError(result);
    else setRuns(result.value.data);
  }

  async function retire() {
    if (!selected || !window.confirm(copy.retireConfirm)) return;
    setBusy("retire");
    setError(null);
    const result = await retireSourceRecipe(selected.id);
    if (result.kind === "error") setError(result);
    else {
      setRecipes((current) => current.filter((item) => item.id !== selected.id));
      resetEditor();
      setNotice(() => (messages: Dictionary) => messages.sourceRecipes.retired);
    }
    setBusy(null);
  }

  function captureImageSize(event: SyntheticEvent<HTMLImageElement>) {
    const image = event.currentTarget;
    setImageSize({ width: Math.max(image.naturalWidth, 1), height: Math.max(image.naturalHeight, 1) });
  }

  function mappingLabel(field: MappingField | null): string {
    if (field === "cardElementId") return copy.mappingCard;
    if (field === "titleElementId") return copy.mappingTitle;
    if (field === "companyElementId") return copy.mappingCompany;
    if (field === "locationElementId") return copy.mappingLocation;
    if (field === "jobUrlElementId") return copy.mappingJobLink;
    return copy.mappingNextPage;
  }

  return (
    <>
      {error ? <ApiErrorState error={error} /> : null}
      {notice ? <p className="status-message" role="status">{notice(dictionary, locale)}</p> : null}

      <section className="content-section source-recipe-policy">
        <div className="section-heading">
          <div><p className="eyebrow">{copy.policyEyebrow}</p><h2>{copy.policyTitle}</h2></div>
          <span className="source-badge">{copy.localOnly}</span>
        </div>
        <p>{copy.policyBody}</p>
      </section>

      <section className="source-recipe-layout">
        <aside>
          <section className="content-section recipe-catalog-card">
            <div className="section-heading"><div><p className="eyebrow">{copy.catalogEyebrow}</p><h2>{copy.catalogTitle}</h2></div><span>{formatNumber(catalog.length, locale)}</span></div>
            <div className="recipe-shortcuts">
              {catalog.map((entry) => <button aria-label={interpolate(copy.useSource, { name: entry.name })} className="button-secondary" key={entry.origin} onClick={() => chooseCatalogEntry(entry)} type="button">{entry.name}</button>)}
            </div>
          </section>
          <section className="content-section">
            <div className="section-heading"><div><p className="eyebrow">{copy.savedEyebrow}</p><h2>{formatNumber(recipes.length, locale)} {copy.recipeCount}</h2></div><button className="button-secondary" onClick={resetEditor} type="button">{copy.newRecipe}</button></div>
            {busy === "loading" && !recipes.length ? <p className="loading-state" role="status">{copy.loading}</p> : recipes.length ? <div className="recipe-list">{recipes.map((recipe) => <button aria-pressed={recipe.id === selectedId} className={`recipe-list-item${recipe.id === selectedId ? " is-selected" : ""}`} key={recipe.id} onClick={() => chooseRecipe(recipe)} type="button"><span><strong>{recipe.name}</strong><small>{recipe.origin}</small></span><span className={`badge ${recipe.status === "blocked" ? "badge-warning" : recipe.status === "enabled" ? "badge-success" : "badge-info"}`}>{statusLabels[recipe.status] ?? recipe.status}</span></button>)}</div> : <EmptyState message={copy.noRecipes} />}
          </section>
          {selected ? <section className="content-section"><div className="section-heading"><div><p className="eyebrow">{copy.historyEyebrow}</p><h2>{copy.recentRuns}</h2></div><button className="button-secondary" disabled={busy !== null} onClick={() => void loadHistory(selected.id)} type="button">{copy.loadHistory}</button></div>{runs.length ? <div className="recipe-run-list">{runs.map((run) => <article className="recipe-run-row" key={run.id}><strong>{statusLabels[run.status] ?? run.status}</strong><span>{statusLabels[run.coverageStatus] ?? run.coverageStatus}</span><time dateTime={run.requestedAt}>{formatDate(run.requestedAt, locale)}</time></article>)}</div> : <EmptyState message={copy.noRuns} />}</section> : null}
        </aside>

        <section className="content-section source-recipe-editor">
          <div className="section-heading"><div><p className="eyebrow">{copy.configureEyebrow}</p><h2>{selected ? copy.editRecipe : copy.createRecipe}</h2></div>{selected ? <span className="badge badge-info">{statusLabels[selected.status] ?? selected.status}</span> : null}</div>
          <form className="source-recipe-form" onSubmit={saveRecipe}>
            <label htmlFor="source-recipe-name">{copy.name}<input id="source-recipe-name" maxLength={200} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} placeholder={copy.namePlaceholder} value={form.name} /></label>
            <label htmlFor="source-recipe-listing-url">{copy.listingUrl}<input disabled={selected !== null} id="source-recipe-listing-url" maxLength={2048} onChange={(event) => setForm((current) => ({ ...current, listingUrl: event.target.value }))} placeholder="https://example.test/jobs" type="url" value={form.listingUrl} /></label>
            <fieldset className="seniority-fieldset"><legend>{copy.seniority}</legend><p className="field-help">{copy.seniorityHelp}</p><div className="seniority-options">{SENIORITY_OPTIONS.map((value) => <label key={value}><input checked={form.seniorityFilter.includes(value)} onChange={() => toggleSeniority(value)} type="checkbox" />{(copy.seniorityLabels as Record<string, string>)[value]}</label>)}</div></fieldset>
            <div className="source-recipe-form-grid">
              <label htmlFor="source-recipe-schedule">{copy.schedule}<select id="source-recipe-schedule" onChange={(event) => changeSchedule(event.target.value as FormState["scheduleKind"])} value={form.scheduleKind}><option value="manual">{copy.scheduleManual}</option><option value="every_6_hours">{copy.scheduleSixHours}</option><option value="daily">{copy.scheduleDaily}</option><option value="weekly">{copy.scheduleWeekly}</option></select></label>
              <label htmlFor="source-recipe-timezone">{copy.timezone}<input id="source-recipe-timezone" maxLength={64} onChange={(event) => setForm((current) => ({ ...current, timezone: event.target.value }))} value={form.timezone} /></label>
            </div>
            {form.scheduleKind === "daily" || form.scheduleKind === "weekly" ? <div className="source-recipe-form-grid"><label htmlFor="source-recipe-time">{copy.localTime}<input id="source-recipe-time" onChange={(event) => setForm((current) => ({ ...current, scheduleLocalTime: event.target.value }))} type="time" value={form.scheduleLocalTime ?? "09:00"} /></label>{form.scheduleKind === "weekly" ? <label htmlFor="source-recipe-weekday">{copy.weekday}<select id="source-recipe-weekday" onChange={(event) => setForm((current) => ({ ...current, scheduleWeekday: Number(event.target.value) }))} value={form.scheduleWeekday ?? 0}>{copy.weekdays.map((label, index) => <option key={label} value={index}>{label}</option>)}</select></label> : null}</div> : null}
            <div className="recipe-actions"><button className="button-primary" disabled={busy !== null || selected?.status === "enabled" || selected?.status === "previewing"} type="submit">{busy === "save" ? copy.saving : copy.save}</button>{selected ? <button className="button-secondary" disabled={busy !== null || selected.status === "enabled" || selected.status === "retired"} onClick={() => void queuePreview()} type="button">{busy === "preview" ? copy.previewing : copy.preview}</button> : null}</div>
          </form>

          {selected ? <section className={`terms-notice terms-${selected.termsNotice}`}><div><strong>{copy.termsTitle}</strong><span>{(copy.termsLabels as Record<string, string>)[selected.termsNotice]}</span></div><p>{copy.termsBody}</p>{selected.termsEvidenceUrl ? <a href={selected.termsEvidenceUrl} rel="noreferrer" target="_blank">{copy.termsEvidence}</a> : <span className="field-help">{copy.noTermsEvidence}</span>}{selected.termsAcknowledgementRequired && !selected.termsAcknowledged ? <label className="terms-acknowledgement"><input checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} type="checkbox" />{copy.acknowledgement}</label> : <span className="badge badge-success">{copy.acknowledged}</span>}</section> : null}

          {selected ? <section aria-labelledby="document-import-title" className="document-import-card"><div><p className="eyebrow">{copy.documentImportEyebrow}</p><h3 id="document-import-title">{copy.documentImportTitle}</h3><p>{copy.documentImportBody}</p></div><form aria-busy={busy === "document-import"} className="document-import-form" onSubmit={importDocument}><label htmlFor="source-recipe-document">{copy.documentImportFile}</label><input accept=".html,.htm,.json,.csv" aria-describedby="source-recipe-document-help" disabled={documentImportDisabled} id="source-recipe-document" key={selected.id} onChange={(event) => setDocumentFile(event.target.files?.[0] ?? null)} type="file" /><p className="field-help" id="source-recipe-document-help">{copy.documentImportHelp}</p><button className="button-primary" disabled={documentImportDisabled || documentFile === null} type="submit">{busy === "document-import" ? copy.documentImporting : copy.documentImportAction}</button></form><div aria-atomic="true" aria-live="polite" className="document-import-live">{documentImportResult ? <div className="document-import-result"><div><strong>{copy.documentImportComplete}</strong><span className="badge badge-info">{statusLabels[documentImportResult.coverage] ?? documentImportResult.coverage}</span></div><dl className="document-import-metrics"><div><dt>{copy.documentImportFound}</dt><dd>{formatNumber(documentImportResult.jobsFound, locale)}</dd></div><div><dt>{copy.documentImportNew}</dt><dd>{formatNumber(documentImportResult.jobsNew, locale)}</dd></div><div><dt>{copy.documentImportUpdated}</dt><dd>{formatNumber(documentImportResult.jobsUpdated, locale)}</dd></div><div><dt>{copy.documentImportUnchanged}</dt><dd>{formatNumber(documentImportResult.jobsUnchanged, locale)}</dd></div><div><dt>{copy.documentImportFiltered}</dt><dd>{formatNumber(documentImportResult.itemsFilteredOut, locale)}</dd></div></dl></div> : null}</div></section> : null}

          {selected?.status === "blocked" ? <div className="api-state api-state--error safe-block-state" role="alert"><strong>{copy.blocked}</strong><p>{copy.blockedBody}</p><small>{selected.blockReason ?? copy.blockedUnknown}</small></div> : null}
          {selected?.cooldownUntil ? <p className="cooldown-state" role="status">{interpolate(copy.cooldownUntil, { date: formatDate(selected.cooldownUntil, locale) })}</p> : null}

          {preview ? <section aria-live="polite" className="recipe-preview"><div className="section-heading"><div><p className="eyebrow">{copy.previewEyebrow}</p><h3>{formatNumber(preview.candidates.length, locale)} {copy.previewJobs}</h3></div><span>{statusLabels[preview.status] ?? preview.status}</span></div>{preview.errorCode ? <p className="api-state api-state--error"><strong>{copy.previewStopped}</strong><span> {preview.errorCode}</span></p> : null}<div className="preview-job-grid">{preview.candidates.slice(0, 5).map((candidate, index) => <article className="preview-job-card" key={candidateKey(candidate, index)}><strong>{candidate.title}</strong><span>{candidate.company}{candidate.location ? ` · ${candidate.location}` : ""}</span><small>{formatPercent(candidate.confidence, locale, 0)} · {candidate.parserVersion}</small><small>{copy.provenance}: {candidate.provenance.map((item) => `${item.fieldName} · ${item.method}`).join(", ")}</small></article>)}</div></section> : null}

          {preview && hasRouteProposal ? <section aria-labelledby="route-proposal-title" className="route-proposal-card"><div><p className="eyebrow">{copy.routeProposalEyebrow}</p><h3 id="route-proposal-title">{copy.routeProposalTitle}</h3><p>{copy.routeProposalBody}</p></div><div className="route-proposal-groups">{preview.proposedHosts.length ? <div><strong>{copy.routeProposalHosts}</strong><ul>{preview.proposedHosts.map((host) => <li className="route-proposal-value" key={host}><code>{host}</code></li>)}</ul></div> : null}{preview.proposedPathPrefixes.length ? <div><strong>{copy.routeProposalPaths}</strong><ul>{preview.proposedPathPrefixes.map((path) => <li className="route-proposal-value" key={path}><code>{path}</code></li>)}</ul></div> : null}</div><button className="button-primary" disabled={busy !== null} onClick={() => void confirmRoutes()} type="button">{busy === "confirm-routes" ? copy.confirmingRoutes : copy.confirmRoutes}</button></section> : null}

          {preview?.screenshotDataUrl && preview.elements.length ? <section className="visual-mapper"><div className="section-heading"><div><p className="eyebrow">{copy.mapperEyebrow}</p><h3>{copy.mapperTitle}</h3></div><span>{mappingStep + 1}/{MAPPING_STEPS.length}</span></div><p>{interpolate(copy.mapperInstruction, { field: mappingLabel(currentMappingField) })}</p><div className="mapping-viewport"><div className="mapping-canvas">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt={copy.mapperImageAlt} onLoad={captureImageSize} src={preview.screenshotDataUrl} />
            <div className="mapping-overlay">{preview.elements.map((element) => <button aria-label={interpolate(copy.chooseElement, { text: element.textSummary || element.tag })} aria-pressed={currentMappingField ? mapping[currentMappingField] === element.elementId : false} className="mapping-overlay-button" key={element.elementId} onClick={() => selectMappingElement(element.elementId)} style={mappingButtonStyle(element, imageSize)} title={element.textSummary} type="button"><span>{element.textSummary || element.tag}</span></button>)}</div></div></div>{currentMappingField === "locationElementId" ? <button className="button-secondary" onClick={markOptionalAbsent} type="button">{copy.locationAbsent}</button> : null}{currentMappingField === "paginationElementId" ? <button className="button-secondary" onClick={markOptionalAbsent} type="button">{copy.singlePage}</button> : null}<div className="mapping-summary">{MAPPING_STEPS.map((field) => <span className={mapping[field] ? "is-complete" : ""} key={field}>{mappingLabel(field)}</span>)}</div><button className="button-primary" disabled={busy !== null} onClick={() => void submitMapping()} type="button">{busy === "mapping" ? copy.savingMapping : copy.saveMapping}</button></section> : null}

          {selected ? <section className="recipe-operations"><div className="section-heading"><div><p className="eyebrow">{copy.operationsEyebrow}</p><h3>{copy.operationsTitle}</h3></div>{selected.nextRunAt ? <time dateTime={selected.nextRunAt}>{interpolate(copy.nextRun, { date: formatDate(selected.nextRunAt, locale) })}</time> : null}</div><div className="recipe-actions"><button disabled={busy !== null || !canCrawl} onClick={() => void crawlNow()} type="button">{copy.crawlNow}</button>{selected.status === "enabled" ? <button className="button-secondary" disabled={busy !== null} onClick={() => void changeStatus("paused")} type="button">{copy.pause}</button> : <button className="button-secondary" disabled={busy !== null || !canEnable || hasRouteProposal} onClick={() => void changeStatus("enabled")} type="button">{selected.status === "paused" ? copy.resume : copy.enable}</button>}<button className="button-danger" disabled={busy !== null} onClick={() => void retire()} type="button">{copy.retire}</button></div></section> : null}
        </section>
      </section>
    </>
  );
}
