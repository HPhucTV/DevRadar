"use client";

import { useEffect, useState } from "react";
import { ApiErrorState, EmptyState, Metric } from "@/components/api-state";
import type { ApiFailure } from "@/lib/api";
import { getIngestionRun, listIngestionRuns, listIngestionSources, requestCrawlRun, type IngestionRun, type IngestionSource } from "@/lib/ingestion";

const POLL_INTERVAL_MS = 2_000;
const POLL_WINDOW_MS = 30_000;
const TERMINAL_RUN_STATUSES = new Set(["succeeded", "partial", "failed", "cancelled"]);

export function IngestionConsole() {
  const [sources, setSources] = useState<IngestionSource[]>([]);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [busySourceId, setBusySourceId] = useState<string | null>(null);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);

  async function refresh() {
    setLoading(true);
    setError(null);
    const [sourceResult, runResult] = await Promise.all([listIngestionSources(), listIngestionRuns()]);
    if (sourceResult.kind === "success") setSources(sourceResult.value.data);
    else setError(sourceResult);
    if (runResult.kind === "success") setRuns(runResult.value.data);
    else if (!error) setError(runResult);
    setLoading(false);
  }

  async function runSource(source: IngestionSource) {
    if (source.approvalStatus !== "approved") return;
    setBusySourceId(source.id);
    setError(null);
    setNotice(null);
    const result = await requestCrawlRun(source.id, `ingestion-${crypto.randomUUID()}`);
    if (result.kind === "error") setError(result);
    else {
      setRuns((current) => [result.value.data, ...current.filter((run) => run.id !== result.value.data.id)]);
      setNotice(`Crawl requested for ${source.name}. It is pending for the bounded worker.`);
      setActiveRunId(result.value.data.id);
    }
    setBusySourceId(null);
  }

  useEffect(() => {
    if (!activeRunId) return;

    const runId = activeRunId;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const startedAt = Date.now();

    async function poll() {
      const result = await getIngestionRun(runId);
      if (cancelled) return;
      if (result.kind === "error") {
        setError(result);
        setActiveRunId(null);
        return;
      }

      const activeRun = result.value.data;
      setRuns((current) => [activeRun, ...current.filter((run) => run.id !== activeRun.id)]);
      if (TERMINAL_RUN_STATUSES.has(activeRun.status)) {
        setNotice(`Crawl ${activeRun.status}.`);
        setActiveRunId(null);
        return;
      }
      if (Date.now() - startedAt >= POLL_WINDOW_MS) {
        setNotice("Crawl is still pending; refresh manually to check again.");
        setActiveRunId(null);
        return;
      }
      timeout = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    }

    void poll();
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [activeRunId]);

  const healthy = sources.filter((source) => source.healthStatus === "healthy").length;
  const degraded = sources.length - healthy;

  return <>
    <section className="content-section">
      <div className="section-heading">
        <div><p className="eyebrow">Operator control</p><h2>Approved sources only</h2></div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>{loading ? "Loading..." : sources.length || runs.length ? "Refresh" : "Load registry"}</button>
      </div>
      <p>Triggering sends only a server-validated source identity. The API owns allow-list, approval, CSRF, operator authorization and idempotency; crawl network work stays outside this request.</p>
    </section>
    {error ? <ApiErrorState error={error} /> : null}
    {notice ? <p className="status-message" role="status">{notice}</p> : null}
    <div className="metric-grid">
      <Metric label="Sources" value={sources.length} />
      <Metric label="Healthy" value={healthy} />
      <Metric label="Needs attention" value={degraded} />
    </div>
    <section className="content-section">
      <div className="section-heading"><div><p className="eyebrow">Allow-list</p><h2>Source health</h2></div><span>{sources.length} loaded</span></div>
      {loading && !sources.length ? <p className="loading-state">Loading source registry...</p> : sources.length ? <div className="source-list">{sources.map((source) => <article className="source-row" key={source.id}><div><strong>{source.name}</strong><p>{source.healthReasonCode ?? "No active health warning"}</p></div><div><span className={`health-pill health-${source.healthStatus}`}>{source.healthStatus}</span><button type="button" onClick={() => void runSource(source)} disabled={loading || busySourceId !== null || source.approvalStatus !== "approved"}>{busySourceId === source.id ? "Requesting..." : source.approvalStatus === "approved" ? "Run now" : "Not approved"}</button></div></article>)}</div> : <EmptyState message="No source registry rows are available." />}
    </section>
    <section className="content-section">
      <div className="section-heading"><div><p className="eyebrow">Workflow history</p><h2>Recent crawl runs</h2></div><span>{runs.length} shown</span></div>
      {runs.length ? <div className="source-list">{runs.map((run) => <article className="source-row" key={run.id}><div><strong>{run.status} · {run.coverageStatus}</strong><p>{run.counts.itemsFound} found · {run.counts.itemsFailed} failed · requested {new Date(run.requestedAt).toLocaleString()}</p></div><span>{run.healthSignalCode ?? "No health signal"}</span></article>)}</div> : <EmptyState message="No crawl runs have been recorded for this operator." />}
    </section>
  </>;
}
