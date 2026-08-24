"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiErrorState } from "@/components/api-state";
import { useI18n } from "@/i18n/locale-provider";
import { formatDate, formatNumber, formatPercent, interpolate } from "@/i18n/locale";
import type { ApiFailure } from "@/lib/api";
import {
  createCustomSource,
  listCustomCrawlRuns,
  listCustomSources,
  previewCustomSource,
  requestCustomCrawl,
  retireCustomSource,
  updateCustomSource,
  type CustomCrawlRun,
  type CustomPreview,
  type CustomSource,
  type CustomSourceInput,
} from "@/lib/custom-sources";

type FormState = Omit<CustomSourceInput, "permission_acknowledged"> & { permission_acknowledged: boolean };

const DEFAULT_FORM: FormState = {
  name: "",
  base_url: "",
  parser_mode: "auto",
  field_mapping: { title: "", company: "", location: "", salary: "", description: "", postedAt: "", externalId: "", jobUrl: "" },
  schedule_kind: "interval",
  interval_minutes: 360,
  daily_at: null,
  timezone: "Asia/Ho_Chi_Minh",
  item_budget: 500,
  byte_budget: 2_000_000,
  requests_per_minute: 2,
  permission_acknowledged: false,
};

const MAPPING_FIELDS = [
  ["title", "mappingTitle"],
  ["company", "mappingCompany"],
  ["location", "mappingLocation"],
  ["salary", "mappingSalary"],
  ["description", "mappingDescription"],
  ["postedAt", "mappingPostedAt"],
  ["externalId", "mappingExternalId"],
  ["jobUrl", "mappingJobUrl"],
] as const;

function toForm(source: CustomSource): FormState {
  return {
    name: source.name,
    base_url: source.baseUrl,
    allowed_hosts: source.allowedHosts,
    allowed_path_prefixes: source.allowedPathPrefixes,
    parser_mode: source.parserMode,
    field_mapping: { ...DEFAULT_FORM.field_mapping, ...source.fieldMapping },
    schedule_kind: source.scheduleKind,
    interval_minutes: source.intervalMinutes,
    daily_at: source.dailyAt,
    timezone: source.timezone,
    item_budget: source.itemBudget,
    byte_budget: source.byteBudget,
    requests_per_minute: source.requestsPerMinute,
    permission_acknowledged: source.permissionAcknowledged,
  };
}

function asInput(form: FormState): CustomSourceInput {
  return {
    ...form,
    permission_acknowledged: true,
    field_mapping: Object.fromEntries(Object.entries(form.field_mapping).filter(([, value]) => value.trim())),
  };
}

function failureFrom(message: string): ApiFailure {
  return { kind: "error", status: 422, code: "custom_source_invalid", message };
}

export function CustomSourcePanel() {
  const { locale, dictionary } = useI18n();
  const statusLabels = dictionary.status as Record<string, string>;
  const [sources, setSources] = useState<CustomSource[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [preview, setPreview] = useState<CustomPreview | null>(null);
  const [runs, setRuns] = useState<CustomCrawlRun[]>([]);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);

  const selected = useMemo(() => sources.find((source) => source.id === selectedId) ?? null, [selectedId, sources]);
  const canEnable = selected?.status === "preview_ready" || selected?.status === "paused";

  useEffect(() => {
    let active = true;
    void listCustomSources().then((result) => {
      if (!active) return;
      if (result.kind === "error") setError(result);
      else setSources(result.value.data);
      setBusy(false);
    });
    return () => { active = false; };
  }, []);

  function chooseSource(source: CustomSource) {
    setSelectedId(source.id);
    setForm(toForm(source));
    setPreview(null);
    setRuns([]);
    setError(null);
    setNotice(null);
  }

  function resetForm() {
    setSelectedId(null);
    setForm(DEFAULT_FORM);
    setPreview(null);
    setRuns([]);
    setError(null);
    setNotice(null);
  }

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function updateMapping(key: string, value: string) {
    setForm((current) => ({ ...current, field_mapping: { ...current.field_mapping, [key]: value } }));
  }

  function changeScheduleKind(value: FormState["schedule_kind"]) {
    setForm((current) => ({
      ...current,
      schedule_kind: value,
      interval_minutes: value === "interval" ? current.interval_minutes ?? 360 : null,
      daily_at: value === "daily_at" ? current.daily_at ?? "09:00" : null,
    }));
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!form.name.trim() || !form.base_url.trim()) {
      setError(failureFrom(dictionary.customSources.validation));
      return;
    }
    if (!form.permission_acknowledged) {
      setError(failureFrom(dictionary.customSources.permissionValidation));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const input = asInput(form);
    const result = selectedId ? await updateCustomSource(selectedId, input) : await createCustomSource(input);
    if (result.kind === "error") setError(result);
    else {
      const source = result.value.data;
      setSources((current) => selectedId ? current.map((item) => item.id === source.id ? source : item) : [source, ...current]);
      setSelectedId(source.id);
      setForm(toForm(source));
      setPreview(null);
      setNotice(dictionary.customSources.saved);
    }
    setBusy(false);
  }

  async function testCrawl() {
    if (!selectedId) {
      setError(failureFrom(dictionary.customSources.saveBeforePreview));
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    const result = await previewCustomSource(selectedId);
    if (result.kind === "error") setError(result);
    else {
      setPreview(result.value.data);
      setSources((current) => current.map((item) => item.id === result.value.data.profile.id ? result.value.data.profile : item));
      setForm(toForm(result.value.data.profile));
      setNotice(result.value.data.candidates.length ? dictionary.customSources.previewSuccess : dictionary.customSources.previewEmpty);
    }
    setBusy(false);
  }

  async function changeStatus(status: "enabled" | "paused") {
    if (!selectedId) return;
    if (status === "enabled" && !canEnable) {
      setError(failureFrom(dictionary.errors.codes.preview_required));
      return;
    }
    setBusy(true);
    setError(null);
    const result = await updateCustomSource(selectedId, { status });
    if (result.kind === "error") setError(result);
    else {
      setSources((current) => current.map((item) => item.id === result.value.data.id ? result.value.data : item));
      setForm(toForm(result.value.data));
      setNotice(status === "enabled" ? dictionary.customSources.scheduleEnabled : dictionary.customSources.schedulePaused);
    }
    setBusy(false);
  }

  async function retire() {
    if (!selectedId || !window.confirm(dictionary.customSources.retireConfirm)) return;
    setBusy(true);
    setError(null);
    const result = await retireCustomSource(selectedId);
    if (result.kind === "error") setError(result);
    else {
      setSources((current) => current.filter((item) => item.id !== selectedId));
      resetForm();
      setNotice(dictionary.customSources.retired);
    }
    setBusy(false);
  }

  async function queueCrawl() {
    if (!selectedId) return;
    setBusy(true);
    setError(null);
    const result = await requestCustomCrawl(selectedId);
    if (result.kind === "error") setError(result);
    else {
      setNotice(interpolate(dictionary.customSources.crawlQueued, { status: statusLabels[result.value.data.status] ?? result.value.data.status }));
      await loadHistory(selectedId);
    }
    setBusy(false);
  }

  async function loadHistory(profileId: string) {
    const result = await listCustomCrawlRuns(profileId);
    if (result.kind === "error") setError(result);
    else setRuns(result.value.data);
  }

  return <>
    {error ? <ApiErrorState error={error} /> : null}
    {notice ? <p className="status-message" role="status">{notice}</p> : null}
    <section className="content-section custom-source-policy">
      <div className="section-heading"><div><p className="eyebrow">{dictionary.customSources.policyEyebrow}</p><h2>{dictionary.customSources.policyTitle}</h2></div><span className="source-badge">{dictionary.customSources.noOverride}</span></div>
      <p>{dictionary.customSources.policyBody}</p>
    </section>
    <section className="custom-source-layout">
      <div>
        <section className="content-section"><div className="section-heading"><div><p className="eyebrow">{dictionary.customSources.savedEyebrow}</p><h2>{formatNumber(sources.length, locale)} {dictionary.customSources.count}</h2></div><button className="button-secondary" type="button" onClick={resetForm}>{dictionary.customSources.newProfile}</button></div>{busy && !sources.length ? <p className="loading-state" role="status">{dictionary.customSources.loadingProfiles}</p> : sources.length ? <div className="custom-source-list">{sources.map((source) => <button className={`custom-source-item${source.id === selectedId ? " is-selected" : ""}`} type="button" key={source.id} onClick={() => chooseSource(source)}><span><strong>{source.name}</strong><small>{source.baseUrl}</small></span><span className={`badge ${source.status === "blocked" ? "badge-warning" : source.status === "enabled" || source.status === "degraded" ? "badge-success" : "badge-info"}`}>{statusLabels[source.status] ?? source.status}</span></button>)}</div> : <div className="api-state empty-state"><strong>{dictionary.customSources.noProfiles}</strong><p>{dictionary.customSources.noProfilesBody}</p></div>}</section>
        {selected ? <section className="content-section"><div className="section-heading"><div><p className="eyebrow">{dictionary.customSources.historyEyebrow}</p><h2>{dictionary.customSources.recentRuns}</h2></div><button className="button-secondary" type="button" onClick={() => void loadHistory(selected.id)} disabled={busy}>{dictionary.customSources.loadHistory}</button></div>{runs.length ? <div className="custom-run-list">{runs.map((run) => <div className="custom-run-row" key={run.id}><strong>{statusLabels[run.status] ?? run.status}</strong><span>{formatDate(run.requestedAt, locale)}</span></div>)}</div> : <div className="api-state empty-state"><strong>{dictionary.customSources.noRuns}</strong><p>{dictionary.customSources.noRunsBody}</p></div>}</section> : null}
      </div>
      <section className="content-section custom-source-editor"><div className="section-heading"><div><p className="eyebrow">{dictionary.customSources.configEyebrow}</p><h2>{selected ? dictionary.customSources.editProfile : dictionary.customSources.createProfile}</h2></div>{selected ? <span className="badge badge-info">{statusLabels[selected.status] ?? selected.status}</span> : null}</div>
        <form className="custom-source-form" onSubmit={save}>
          <label htmlFor="custom-source-name">{dictionary.customSources.name}<input id="custom-source-name" value={form.name} onChange={(event) => updateField("name", event.target.value)} maxLength={200} placeholder={dictionary.customSources.namePlaceholder} /></label>
          <label htmlFor="custom-source-url">{dictionary.customSources.url}<input id="custom-source-url" type="url" value={form.base_url} onChange={(event) => updateField("base_url", event.target.value)} maxLength={2048} placeholder={dictionary.customSources.urlPlaceholder} /></label>
          <div className="custom-source-form-grid"><label htmlFor="custom-parser-mode">{dictionary.customSources.parserMode}<select id="custom-parser-mode" value={form.parser_mode} onChange={(event) => updateField("parser_mode", event.target.value as FormState["parser_mode"])}><option value="auto">{dictionary.status.auto}</option><option value="json">{dictionary.status.json}</option><option value="html">{dictionary.status.html}</option></select></label><label htmlFor="custom-schedule-kind">{dictionary.customSources.schedule}<select id="custom-schedule-kind" value={form.schedule_kind} onChange={(event) => changeScheduleKind(event.target.value as FormState["schedule_kind"])}><option value="interval">{dictionary.status.interval}</option><option value="daily_at">{dictionary.status.daily_at}</option></select></label></div>
          {form.schedule_kind === "interval" ? <label htmlFor="custom-interval">{dictionary.customSources.intervalMinutes}<input id="custom-interval" type="number" min={5} max={10080} value={form.interval_minutes ?? 360} onChange={(event) => updateField("interval_minutes", Number(event.target.value))} /></label> : <div className="custom-source-form-grid"><label htmlFor="custom-daily-at">{dictionary.customSources.localTime}<input id="custom-daily-at" type="time" value={form.daily_at ?? "09:00"} onChange={(event) => updateField("daily_at", event.target.value)} /></label><label htmlFor="custom-timezone">{dictionary.customSources.timezone}<input id="custom-timezone" value={form.timezone} onChange={(event) => updateField("timezone", event.target.value)} maxLength={64} /></label></div>}
          <fieldset><legend>{dictionary.customSources.mapping}</legend><p className="field-help">{dictionary.customSources.mappingHelp}</p><div className="custom-mapping-grid">{MAPPING_FIELDS.map(([key, label]) => <label key={key} htmlFor={`custom-mapping-${key}`}>{key}<input id={`custom-mapping-${key}`} value={form.field_mapping[key] ?? ""} onChange={(event) => updateMapping(key, event.target.value)} maxLength={500} placeholder={dictionary.customSources[label]} /></label>)}</div></fieldset>
          <div className="custom-source-form-grid"><label htmlFor="custom-item-budget">{dictionary.customSources.itemBudget}<input id="custom-item-budget" type="number" min={1} max={10000} value={form.item_budget} onChange={(event) => updateField("item_budget", Number(event.target.value))} /></label><label htmlFor="custom-byte-budget">{dictionary.customSources.byteBudget}<input id="custom-byte-budget" type="number" min={1} max={10000000} value={form.byte_budget} onChange={(event) => updateField("byte_budget", Number(event.target.value))} /></label><label htmlFor="custom-rate-limit">{dictionary.customSources.rateLimit}<input id="custom-rate-limit" type="number" min={1} max={60} value={form.requests_per_minute} onChange={(event) => updateField("requests_per_minute", Number(event.target.value))} /></label></div>
          <label className="custom-permission"><input type="checkbox" checked={form.permission_acknowledged} onChange={(event) => updateField("permission_acknowledged", event.target.checked)} /> {dictionary.customSources.permission}</label>
          <div className="custom-source-actions"><button className="button-primary" type="submit" disabled={busy || !form.permission_acknowledged}>{busy ? dictionary.customSources.saving : dictionary.customSources.save}</button>{selected ? <><button className="button-secondary" type="button" onClick={() => void testCrawl()} disabled={busy}>{dictionary.customSources.testCrawl}</button><button className="button-secondary" type="button" onClick={() => void queueCrawl()} disabled={busy || !["enabled", "degraded"].includes(selected.status)}>{dictionary.customSources.queueCrawl}</button>{selected.status === "enabled" || selected.status === "degraded" ? <button className="button-secondary" type="button" onClick={() => void changeStatus("paused")} disabled={busy}>{dictionary.common.pause}</button> : <button className="button-secondary" type="button" onClick={() => void changeStatus("enabled")} disabled={busy || !canEnable}>{dictionary.customSources.enableSchedule}</button>}<button className="button-danger" type="button" onClick={() => void retire()} disabled={busy}>{dictionary.customSources.retire}</button></> : null}</div>
        </form>
        {selected?.status === "blocked" ? <p className="api-state api-state--error" role="alert"><strong>{dictionary.customSources.accessRequired}</strong><span> {dictionary.customSources.blockedBody}</span></p> : null}
        {preview ? <div className="custom-preview" aria-live="polite"><div className="section-heading"><div><p className="eyebrow">{dictionary.customSources.previewEyebrow}</p><h3>{formatNumber(preview.candidates.length, locale)} {dictionary.customSources.candidates}</h3></div><span>{preview.profile.parserVersion}</span></div><p className="field-help">{dictionary.customSources.coverage}: {statusLabels[preview.coverageStatus] ?? preview.coverageStatus}. {dictionary.customSources.finalUrl}: {preview.finalUrl ?? dictionary.customSources.unavailable}. {dictionary.customSources.redirects}: {formatNumber(preview.redirectChain.length, locale)}.</p>{preview.failures.length ? <div className="api-state api-state--error"><strong>{dictionary.customSources.previewStopped}</strong><p>{preview.failures.map((failure) => `${failure.code}: ${failure.message}`).join("; ")}</p></div> : null}{preview.candidates.slice(0, 5).map((candidate, index) => <article className="custom-preview-card" key={`${candidate.externalId}:${index}`}><strong>{candidate.title}</strong><span>{candidate.company}{candidate.location ? ` · ${candidate.location}` : ""}</span><small>{candidate.jobUrl} · {dictionary.customSources.confidence} {formatPercent(candidate.confidence, locale, 0)}{candidate.warnings.length ? ` · ${dictionary.customSources.warnings}: ${candidate.warnings.join(", ")}` : ""}</small><small>{dictionary.customSources.provenance}: {candidate.provenance.map((item) => `${item.fieldName} ${dictionary.customSources.via} ${item.method} ${dictionary.customSources.at} ${item.sourcePath}`).join(", ") || dictionary.customSources.provenanceUnavailable}</small></article>)}</div> : null}
      </section>
    </section>
  </>;
}
