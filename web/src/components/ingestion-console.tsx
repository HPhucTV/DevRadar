"use client";

import { useState } from "react";
import { ApiErrorState, EmptyState, Metric } from "@/components/api-state";
import type { Dictionary } from "@/i18n/dictionaries";
import { useI18n } from "@/i18n/locale-provider";
import { formatDate, formatNumber, type Locale } from "@/i18n/locale";
import type { ApiFailure } from "@/lib/api";
import { listIngestionRuns, listIngestionSources, type IngestionRun, type IngestionSource } from "@/lib/ingestion";

type Notice = (dictionary: Dictionary, locale: Locale) => string;

export function IngestionConsole() {
  const { locale, dictionary } = useI18n();
  const statusLabels = dictionary.status as Record<string, string>;
  const [sources, setSources] = useState<IngestionSource[]>([]);
  const [runs, setRuns] = useState<IngestionRun[]>([]);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    setError(null);
    const [sourceResult, runResult] = await Promise.all([listIngestionSources(), listIngestionRuns()]);
    if (sourceResult.kind === "success") setSources(sourceResult.value.data);
    else setError(sourceResult);
    if (runResult.kind === "success") setRuns(runResult.value.data);
    else if (!error) setError(runResult);
    if (sourceResult.kind === "success" && runResult.kind === "success") {
      setNotice(() => (messages: Dictionary) => messages.crawler.refreshed);
    }
    setLoading(false);
  }

  const healthy = sources.filter((source) => source.healthStatus === "healthy").length;
  const degraded = sources.length - healthy;

  return <>
    <section className="content-section source-health-intro">
      <div className="section-heading">
        <div><p className="eyebrow">{dictionary.crawler.controlEyebrow}</p><h2>{dictionary.crawler.readOnly}</h2></div>
        <button type="button" onClick={() => void refresh()} disabled={loading}>{loading ? dictionary.common.loading : sources.length || runs.length ? dictionary.common.refresh : dictionary.crawler.loadRegistry}</button>
      </div>
      <p>{dictionary.crawler.policyBody}</p>
    </section>
    {error ? <ApiErrorState error={error} /> : null}
    {notice ? <p className="status-message" role="status">{notice(dictionary, locale)}</p> : null}
    <div className="health-grid metric-grid">
      <Metric label={dictionary.crawler.sources} value={formatNumber(sources.length, locale)} />
      <Metric label={dictionary.crawler.healthy} value={formatNumber(healthy, locale)} />
      <Metric label={dictionary.crawler.attention} value={formatNumber(degraded, locale)} />
    </div>
    <section className="content-section">
      <div className="section-heading"><div><p className="eyebrow">{dictionary.crawler.allowlist}</p><h2>{dictionary.crawler.sourceHealth}</h2></div><span>{formatNumber(sources.length, locale)} {dictionary.common.loaded}</span></div>
      {loading && !sources.length ? <p className="loading-state">{dictionary.crawler.loadingRegistry}</p> : sources.length ? <div className="source-list health-source-list">{sources.map((source) => <article className="source-card source-row" key={source.id}><div><strong>{source.name}</strong><p>{source.healthReasonCode ?? dictionary.crawler.noHealthWarning}</p></div><div className="source-health-labels"><span className={`health-pill health-${source.healthStatus}`}>{statusLabels[source.healthStatus] ?? source.healthStatus}</span><span className="source-badge">{statusLabels[source.approvalStatus] ?? source.approvalStatus}</span></div></article>)}</div> : <EmptyState message={dictionary.crawler.noSources} />}
    </section>
    <section className="content-section">
      <div className="section-heading"><div><p className="eyebrow">{dictionary.crawler.historyEyebrow}</p><h2>{dictionary.crawler.recentRuns}</h2></div><span>{formatNumber(runs.length, locale)} {dictionary.common.shown}</span></div>
      {runs.length ? <div className="run-timeline source-list">{runs.map((run) => <article className="run-card source-row" key={run.id}><div><strong>{statusLabels[run.status] ?? run.status} · {statusLabels[run.coverageStatus] ?? run.coverageStatus}</strong><p>{formatNumber(run.counts.itemsFound, locale)} {dictionary.crawler.found} · {formatNumber(run.counts.itemsFailed, locale)} {dictionary.crawler.failed} · {dictionary.crawler.requested} {formatDate(run.requestedAt, locale)}</p></div><span>{run.healthSignalCode ?? dictionary.crawler.noHealthSignal}</span></article>)}</div> : <EmptyState message={dictionary.crawler.noRuns} />}
    </section>
  </>;
}
