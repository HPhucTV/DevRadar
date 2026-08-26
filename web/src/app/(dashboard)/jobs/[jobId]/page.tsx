import Link from "next/link";
import { ApiErrorState, EmptyState } from "@/components/api-state";
import { formatDate, formatNumber } from "@/i18n/locale";
import { getI18n } from "@/i18n/server";
import { getJob, listJobChanges } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function JobDetailPage({ params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  const [{ locale, dictionary }, job, changes] = await Promise.all([
    getI18n(),
    getJob(jobId),
    listJobChanges(jobId),
  ]);
  if (job.kind === "error") return <ApiErrorState error={job} />;
  const item = job.value.data;
  const statusLabels = dictionary.status as Record<string, string>;
  const fieldLabels = dictionary.jobDetail.fields as Record<string, string>;
  return <div className="detail-inspector-page">
    <Link className="detail-back-link" href="/jobs">{dictionary.jobDetail.back}</Link>
    <section className="route-header route-header--compact">
      <p className="route-label">{item.source.name}</p>
      <h1>{item.title}</h1>
      <p>{item.companyName} · {item.location.city ?? item.location.raw ?? dictionary.jobs.locationMissing}</p>
    </section>
    <section className="detail-grid">
      <article className="data-surface glass-surface detail-main">
        <div className="section-heading">
          <div><p className="route-label">{dictionary.jobDetail.descriptionEyebrow}</p><h2>{dictionary.jobDetail.description}</h2></div>
          {item.salary.raw ? <span className="salary-badge">{item.salary.raw}</span> : null}
        </div>
        <p className="description-text">{item.descriptionText ?? dictionary.jobDetail.descriptionMissing}</p>
      </article>
      <aside className="detail-aside glass-surface provenance-card">
        <div className="section-heading"><div><p className="route-label">{dictionary.jobDetail.evidenceEyebrow}</p><h2>{dictionary.jobDetail.provenance}</h2></div></div>
        <dl>
          <dt>{dictionary.jobDetail.observed}</dt><dd>{formatDate(item.lastSeenAt, locale)}</dd>
          <dt>{dictionary.jobDetail.snapshot}</dt><dd><a href={item.currentSnapshot.sourceUrl} rel="noreferrer">{dictionary.jobDetail.originalSource}</a></dd>
          <dt>{dictionary.jobDetail.parseStatus}</dt><dd>{statusLabels[item.currentSnapshot.parseStatus] ?? item.currentSnapshot.parseStatus}</dd>
        </dl>
      </aside>
    </section>
    <section className="data-surface glass-surface">
      <div className="section-heading">
        <div><p className="route-label">{dictionary.jobDetail.auditEyebrow}</p><h2>{dictionary.jobDetail.history}</h2></div>
        <span>{changes.kind === "success" ? `${formatNumber(changes.value.pagination.totalItems, locale)} ${dictionary.common.events}` : dictionary.common.unavailable}</span>
      </div>
      {changes.kind === "success"
        ? changes.value.data.length
          ? <div className="change-list source-list">{changes.value.data.map((change) => <div className="source-row" key={change.id}><strong>{statusLabels[change.changeType] ?? change.changeType} · {fieldLabels[change.fieldName] ?? change.fieldName}</strong><span>{formatDate(change.detectedAt, locale, { dateStyle: "medium" })}</span></div>)}</div>
          : <EmptyState message={dictionary.jobDetail.noChanges} />
        : <ApiErrorState error={changes} />}
    </section>
  </div>;
}
