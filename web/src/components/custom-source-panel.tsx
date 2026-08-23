"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ApiErrorState } from "@/components/api-state";
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
  ["title", "Title selector or JSON path"],
  ["company", "Company selector or JSON path"],
  ["location", "Location selector or JSON path"],
  ["salary", "Salary selector or JSON path"],
  ["description", "Description selector or JSON path"],
  ["postedAt", "Posted-at selector or JSON path"],
  ["externalId", "External ID selector or JSON path"],
  ["jobUrl", "Job URL selector or JSON path"],
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

function statusLabel(status: string): string {
  return status.replaceAll("_", " ");
}

function failureFrom(message: string): ApiFailure {
  return { kind: "error", status: 422, code: "custom_source_invalid", message };
}

export function CustomSourcePanel() {
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
      setError(failureFrom("Add a name and an HTTPS source URL."));
      return;
    }
    if (!form.permission_acknowledged) {
      setError(failureFrom("Confirm that you have permission to access this source."));
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
      setNotice("Profile saved. Run Test crawl before enabling its schedule.");
    }
    setBusy(false);
  }

  async function testCrawl() {
    if (!selectedId) {
      setError(failureFrom("Save the profile before running Test crawl."));
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
      setNotice(result.value.data.candidates.length ? "Preview succeeded. The schedule can now be enabled." : "Preview completed without candidates.");
    }
    setBusy(false);
  }

  async function changeStatus(status: "enabled" | "paused") {
    if (!selectedId) return;
    if (status === "enabled" && !canEnable) {
      setError(failureFrom("A successful preview is required before enabling the schedule."));
      return;
    }
    setBusy(true);
    setError(null);
    const result = await updateCustomSource(selectedId, { status });
    if (result.kind === "error") setError(result);
    else {
      setSources((current) => current.map((item) => item.id === result.value.data.id ? result.value.data : item));
      setForm(toForm(result.value.data));
      setNotice(status === "enabled" ? "Schedule enabled." : "Schedule paused.");
    }
    setBusy(false);
  }

  async function retire() {
    if (!selectedId || !window.confirm("Retire this custom source? Historical jobs stay preserved.")) return;
    setBusy(true);
    setError(null);
    const result = await retireCustomSource(selectedId);
    if (result.kind === "error") setError(result);
    else {
      setSources((current) => current.filter((item) => item.id !== selectedId));
      resetForm();
      setNotice("Custom source retired. Historical data was preserved.");
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
      setNotice(`Crawl queued with status ${result.value.data.status}.`);
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
      <div className="section-heading"><div><p className="eyebrow">Local and protected</p><h2>Connect a source you are allowed to access</h2></div><span className="source-badge">No access override</span></div>
      <p>DevRadar stores the URL boundary and parser mapping. CAPTCHA, sign-in, paywall and anti-bot responses stop the profile for review.</p>
    </section>
    <section className="custom-source-layout">
      <div>
        <section className="content-section"><div className="section-heading"><div><p className="eyebrow">Saved profiles</p><h2>{sources.length} custom sources</h2></div><button className="button-secondary" type="button" onClick={resetForm}>New profile</button></div>{busy && !sources.length ? <p className="loading-state" role="status">Loading profiles...</p> : sources.length ? <div className="custom-source-list">{sources.map((source) => <button className={`custom-source-item${source.id === selectedId ? " is-selected" : ""}`} type="button" key={source.id} onClick={() => chooseSource(source)}><span><strong>{source.name}</strong><small>{source.baseUrl}</small></span><span className={`badge ${source.status === "blocked" ? "badge-warning" : source.status === "enabled" || source.status === "degraded" ? "badge-success" : "badge-info"}`}>{statusLabel(source.status)}</span></button>)}</div> : <div className="api-state empty-state"><strong>No profiles yet</strong><p>Save one profile after confirming its access permission.</p></div>}</section>
        {selected ? <section className="content-section"><div className="section-heading"><div><p className="eyebrow">Crawl history</p><h2>Recent runs</h2></div><button className="button-secondary" type="button" onClick={() => void loadHistory(selected.id)} disabled={busy}>Load history</button></div>{runs.length ? <div className="custom-run-list">{runs.map((run) => <div className="custom-run-row" key={run.id}><strong>{statusLabel(run.status)}</strong><span>{new Date(run.requestedAt).toLocaleString("vi-VN")}</span></div>)}</div> : <div className="api-state empty-state"><strong>No runs loaded</strong><p>Load history after a preview or queued crawl.</p></div>}</section> : null}
      </div>
      <section className="content-section custom-source-editor"><div className="section-heading"><div><p className="eyebrow">Bounded configuration</p><h2>{selected ? "Edit profile" : "Create profile"}</h2></div>{selected ? <span className="badge badge-info">{statusLabel(selected.status)}</span> : null}</div>
        <form className="custom-source-form" onSubmit={save}>
          <label htmlFor="custom-source-name">Profile name<input id="custom-source-name" value={form.name} onChange={(event) => updateField("name", event.target.value)} maxLength={200} placeholder="Example careers" /></label>
          <label htmlFor="custom-source-url">HTTPS source URL<input id="custom-source-url" type="url" value={form.base_url} onChange={(event) => updateField("base_url", event.target.value)} maxLength={2048} placeholder="https://example.test/jobs" /></label>
          <div className="custom-source-form-grid"><label htmlFor="custom-parser-mode">Parser mode<select id="custom-parser-mode" value={form.parser_mode} onChange={(event) => updateField("parser_mode", event.target.value as FormState["parser_mode"])}><option value="auto">Auto: JSON, JSON-LD, HTML</option><option value="json">JSON or API</option><option value="html">HTML mapping</option></select></label><label htmlFor="custom-schedule-kind">Schedule<select id="custom-schedule-kind" value={form.schedule_kind} onChange={(event) => changeScheduleKind(event.target.value as FormState["schedule_kind"])}><option value="interval">Every interval</option><option value="daily_at">Daily at local time</option></select></label></div>
          {form.schedule_kind === "interval" ? <label htmlFor="custom-interval">Interval minutes<input id="custom-interval" type="number" min={5} max={10080} value={form.interval_minutes ?? 360} onChange={(event) => updateField("interval_minutes", Number(event.target.value))} /></label> : <div className="custom-source-form-grid"><label htmlFor="custom-daily-at">Local time<input id="custom-daily-at" type="time" value={form.daily_at ?? "09:00"} onChange={(event) => updateField("daily_at", event.target.value)} /></label><label htmlFor="custom-timezone">Timezone<input id="custom-timezone" value={form.timezone} onChange={(event) => updateField("timezone", event.target.value)} maxLength={64} /></label></div>}
          <fieldset><legend>Field mapping</legend><p className="field-help">Optional selectors or JSON paths. JSON paths are relative to each job record. Empty fields use deterministic auto-detection.</p><div className="custom-mapping-grid">{MAPPING_FIELDS.map(([key, label]) => <label key={key} htmlFor={`custom-mapping-${key}`}>{key}<input id={`custom-mapping-${key}`} value={form.field_mapping[key] ?? ""} onChange={(event) => updateMapping(key, event.target.value)} maxLength={500} placeholder={label} /></label>)}</div></fieldset>
          <div className="custom-source-form-grid"><label htmlFor="custom-item-budget">Item budget<input id="custom-item-budget" type="number" min={1} max={10000} value={form.item_budget} onChange={(event) => updateField("item_budget", Number(event.target.value))} /></label><label htmlFor="custom-byte-budget">Response byte budget<input id="custom-byte-budget" type="number" min={1} max={10000000} value={form.byte_budget} onChange={(event) => updateField("byte_budget", Number(event.target.value))} /></label><label htmlFor="custom-rate-limit">Requests per minute<input id="custom-rate-limit" type="number" min={1} max={60} value={form.requests_per_minute} onChange={(event) => updateField("requests_per_minute", Number(event.target.value))} /></label></div>
          <label className="custom-permission"><input type="checkbox" checked={form.permission_acknowledged} onChange={(event) => updateField("permission_acknowledged", event.target.checked)} /> I confirm I have permission to access this source and will respect its published rules.</label>
          <div className="custom-source-actions"><button className="button-primary" type="submit" disabled={busy || !form.permission_acknowledged}>{busy ? "Saving..." : "Save profile"}</button>{selected ? <><button className="button-secondary" type="button" onClick={() => void testCrawl()} disabled={busy}>Test crawl</button><button className="button-secondary" type="button" onClick={() => void queueCrawl()} disabled={busy || !["enabled", "degraded"].includes(selected.status)}>Queue crawl</button>{selected.status === "enabled" || selected.status === "degraded" ? <button className="button-secondary" type="button" onClick={() => void changeStatus("paused")} disabled={busy}>Pause</button> : <button className="button-secondary" type="button" onClick={() => void changeStatus("enabled")} disabled={busy || !canEnable}>Enable schedule</button>}<button className="button-danger" type="button" onClick={() => void retire()} disabled={busy}>Retire</button></> : null}</div>
        </form>
        {selected?.status === "blocked" ? <p className="api-state api-state--error" role="alert"><strong>Access required</strong><span> This profile is blocked because the last response required permission. Fix access at the source, then run Test crawl again.</span></p> : null}
        {preview ? <div className="custom-preview" aria-live="polite"><div className="section-heading"><div><p className="eyebrow">Preview evidence</p><h3>{preview.candidates.length} candidates</h3></div><span>{preview.profile.parserVersion}</span></div><p className="field-help">Coverage: {preview.coverageStatus}. Final URL: {preview.finalUrl ?? "unavailable"}. Redirects: {preview.redirectChain.length}.</p>{preview.failures.length ? <div className="api-state api-state--error"><strong>Preview stopped safely</strong><p>{preview.failures.map((failure) => `${failure.code}: ${failure.message}`).join("; ")}</p></div> : null}{preview.candidates.slice(0, 5).map((candidate, index) => <article className="custom-preview-card" key={`${candidate.externalId}:${index}`}><strong>{candidate.title}</strong><span>{candidate.company}{candidate.location ? ` · ${candidate.location}` : ""}</span><small>{candidate.jobUrl} · confidence {Math.round(candidate.confidence * 100)}%{candidate.warnings.length ? ` · warnings: ${candidate.warnings.join(", ")}` : ""}</small><small>Provenance: {candidate.provenance.map((item) => `${item.fieldName} via ${item.method} at ${item.sourcePath}`).join(", ") || "unavailable"}</small></article>)}</div> : null}
      </section>
    </section>
  </>;
}
