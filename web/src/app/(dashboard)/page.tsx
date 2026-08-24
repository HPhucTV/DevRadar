import Link from "next/link";
import { ApiErrorState, EmptyState, Metric } from "@/components/api-state";
import { JobList } from "@/components/job-list";
import { formatNumber, formatPercent } from "@/i18n/locale";
import { getI18n } from "@/i18n/server";
import { listJobs, listSkills, listSources } from "@/lib/api";

export const dynamic = "force-dynamic";
export default async function OverviewPage() {
  const [{ locale, dictionary }, jobs, sources, skills] = await Promise.all([getI18n(), listJobs({ pageSize: 5 }), listSources(), listSkills()]);
  const topSkills = skills.kind === "success" ? skills.value.data.slice(0, 5) : [];
  return <>
    <section className="page-intro"><p className="eyebrow">{dictionary.overview.eyebrow}</p><h1>{dictionary.overview.title}</h1><p>{dictionary.overview.body}</p></section>
    <div className="kpi-grid">
      {sources.kind === "success" ? <Metric label={dictionary.overview.approvedSources} value={formatNumber(sources.value.data.filter((item) => item.approvalStatus === "approved").length, locale)} /> : <Metric label={dictionary.overview.sources} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
      {skills.kind === "success" ? <Metric label={dictionary.overview.trackedSkills} value={formatNumber(skills.value.pagination.totalItems, locale)} note={`${dictionary.common.coverage} ${formatPercent(skills.value.meta.coverage, locale)}`} /> : <Metric label={dictionary.overview.skills} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
      {jobs.kind === "success" ? <Metric label={dictionary.overview.visibleJobs} value={formatNumber(jobs.value.pagination.totalItems, locale)} /> : <Metric label={dictionary.overview.jobs} value={dictionary.common.unavailable} note={dictionary.common.apiUnavailable} />}
    </div>
    <div className="dashboard-grid">
      <section className="content-section dashboard-chart-panel">
        <div className="section-heading"><div><p className="eyebrow">{dictionary.overview.demandEyebrow}</p><h2>{dictionary.overview.demandTitle}</h2></div><span>{skills.kind === "success" ? `${formatNumber(skills.value.meta.analyzedJobs, locale)} ${dictionary.common.analyzed}` : dictionary.common.unavailable}</span></div>
        {skills.kind === "success" && topSkills.length ? <div className="skill-demand-list">{topSkills.map((skill) => <div className="skill-demand-row" key={skill.name}><div className="skill-demand-label"><strong>{skill.name}</strong><span>{formatNumber(skill.jobCount, locale)} {dictionary.common.jobs} · {formatPercent(skill.share, locale)}</span></div><div aria-hidden="true" className="skill-demand-track"><span style={{ width: `${Math.max(6, Math.min(100, skill.share * 100))}%` }} /></div></div>)}</div> : skills.kind === "success" ? <EmptyState message={dictionary.overview.noSkills} /> : <ApiErrorState error={skills} />}
      </section>
      <section className="content-section dashboard-feed-panel"><div className="section-heading"><div><p className="eyebrow">{dictionary.overview.latestEyebrow}</p><h2>{dictionary.overview.latestTitle}</h2></div><Link href="/jobs">{dictionary.overview.explore}</Link></div>{jobs.kind === "success" ? jobs.value.data.length ? <JobList jobs={jobs.value.data} /> : <EmptyState message={dictionary.overview.noJobs} /> : <ApiErrorState error={jobs} />}</section>
    </div>
  </>;
}
