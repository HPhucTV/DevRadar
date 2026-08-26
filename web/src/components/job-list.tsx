"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useI18n } from "@/i18n/locale-provider";
import { formatDate } from "@/i18n/locale";
import type { Job } from "@/lib/api";
import { sourceDisplayName } from "@/lib/source-display";

export function JobList({ jobs, compact = false }: { jobs: Job[]; compact?: boolean }) {
  const { locale, dictionary } = useI18n();
  const statusLabels = dictionary.status as Record<string, string>;
  const [selected, setSelected] = useState<Job | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  function openInspector(job: Job, trigger: HTMLButtonElement) {
    triggerRef.current = trigger;
    setSelected(job);
  }

  function closeInspector() {
    setSelected(null);
    requestAnimationFrame(() => triggerRef.current?.focus());
  }

  function handleInspectorKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeInspector();
    }
  }

  useEffect(() => {
    if (!selected) return;
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeInspector();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected]);

  return <div className={`job-explorer${compact ? " is-compact" : ""}${selected ? " has-inspector" : ""}`}>
    <div className="job-table" role="table">
      <div className="job-table-row job-table-header" role="row">
        <span role="columnheader">{dictionary.jobs.titleColumn}</span>
        <span role="columnheader">{dictionary.jobs.companyColumn}</span>
        <span role="columnheader">{dictionary.jobs.levelsLabel}</span>
        <span role="columnheader">{dictionary.jobs.statusLabel}</span>
        <span role="columnheader">{dictionary.jobs.sourceLabel}</span>
      </div>
      {jobs.map((job) => {
        const sourceName = sourceDisplayName(job.source);
        const location = job.location.city ?? job.location.raw ?? dictionary.jobs.locationMissing;
        return <article className="job-table-row" key={job.id} role="row">
          <div className="job-primary-cell" role="cell">
            {compact
              ? <Link className="compact-job-link" href={`/jobs/${job.id}`}>{job.title}</Link>
              : <>
                <button
                  aria-controls="job-summary-inspector"
                  aria-expanded={selected?.id === job.id}
                  className="desktop-job-trigger"
                  onClick={(event) => openInspector(job, event.currentTarget)}
                  type="button"
                >
                  {job.title}
                </button>
                <Link className="mobile-job-link" href={`/jobs/${job.id}`}>{job.title}</Link>
              </>}
            <span>{location} · <span title={job.source.name}>{sourceName}</span> · {formatDate(job.lastSeenAt, locale, { dateStyle: "medium" })}</span>
          </div>
          <span className="job-company-cell" role="cell">{job.companyName}</span>
          <div className="level-list" aria-label={dictionary.jobs.levelsLabel} role="cell">
            {job.levels.length
              ? job.levels.map((level) => <span className="level-badge" key={level}>{level}</span>)
              : <span className="level-badge">{dictionary.jobs.levelMissing}</span>}
          </div>
          <span className="job-status-cell" role="cell">{statusLabels[job.status] ?? job.status}</span>
          <span className="job-source-cell" role="cell" title={job.source.name}>{sourceName}</span>
        </article>;
      })}
    </div>
    {!compact && selected ? <aside
      aria-labelledby="job-inspector-title"
      className="job-inspector glass-surface"
      id="job-summary-inspector"
      onKeyDown={handleInspectorKeyDown}
    >
      <div className="job-inspector-header">
        <p className="route-label">{dictionary.jobs.quickView}</p>
        <button aria-label={dictionary.jobs.closeQuickView} onClick={closeInspector} type="button">×</button>
      </div>
      <h2 id="job-inspector-title">{selected.title}</h2>
      <dl>
        <dt>{dictionary.jobs.companyColumn}</dt><dd>{selected.companyName}</dd>
        <dt>{dictionary.jobs.location}</dt><dd>{selected.location.city ?? selected.location.raw ?? dictionary.jobs.locationMissing}</dd>
        <dt>{dictionary.jobs.statusLabel}</dt><dd>{statusLabels[selected.status] ?? selected.status}</dd>
        <dt>{dictionary.jobs.sourceLabel}</dt><dd title={selected.source.name}>{sourceDisplayName(selected.source)}</dd>
        <dt>{dictionary.jobs.lastSeen}</dt><dd>{formatDate(selected.lastSeenAt, locale)}</dd>
      </dl>
      <Link className="button-primary inspector-detail-link" href={`/jobs/${selected.id}`}>{dictionary.jobs.openFullDetails}</Link>
    </aside> : null}
  </div>;
}
