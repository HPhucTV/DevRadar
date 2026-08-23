import Link from "next/link";
import { ApiErrorState, EmptyState, Metric } from "@/components/api-state";
import { JobList } from "@/components/job-list";
import { listJobs, listSkills, listSources } from "@/lib/api";

export const dynamic = "force-dynamic";
export default async function OverviewPage() {
  const [jobs, sources, skills] = await Promise.all([listJobs({ pageSize: 5 }), listSources(), listSkills()]);
  const topSkills = skills.kind === "success" ? skills.value.data.slice(0, 5) : [];
  return <>
    <section className="page-intro"><p className="eyebrow">Current inventory</p><h1>Make the market legible.</h1><p>Overview uses the approved-source catalog and canonical API responses. Cohort and coverage stay visible when analytics arrives.</p></section>
    <div className="kpi-grid">
      {sources.kind === "success" ? <Metric label="Approved sources" value={sources.value.data.filter((item) => item.approvalStatus === "approved").length} /> : <Metric label="Sources" value="Unavailable" note="API unavailable" />}
      {skills.kind === "success" ? <Metric label="Tracked skills" value={skills.value.pagination.totalItems} note={`Coverage ${(skills.value.meta.coverage * 100).toFixed(1)}%`} /> : <Metric label="Skills" value="Unavailable" note="API unavailable" />}
      {jobs.kind === "success" ? <Metric label="Visible jobs" value={jobs.value.pagination.totalItems} /> : <Metric label="Jobs" value="Unavailable" note="API unavailable" />}
    </div>
    <div className="dashboard-grid">
      <section className="content-section dashboard-chart-panel">
        <div className="section-heading"><div><p className="eyebrow">Evidence-backed demand</p><h2>Skills in the current cohort</h2></div><span>{skills.kind === "success" ? `${skills.value.meta.analyzedJobs} analyzed` : "Unavailable"}</span></div>
        {skills.kind === "success" && topSkills.length ? <div className="skill-demand-list">{topSkills.map((skill) => <div className="skill-demand-row" key={skill.name}><div className="skill-demand-label"><strong>{skill.name}</strong><span>{skill.jobCount} jobs · {(skill.share * 100).toFixed(1)}%</span></div><div aria-hidden="true" className="skill-demand-track"><span style={{ width: `${Math.max(6, Math.min(100, skill.share * 100))}%` }} /></div></div>)}</div> : skills.kind === "success" ? <EmptyState message="No accepted extraction data is available for this cohort." /> : <ApiErrorState error={skills} />}
      </section>
      <section className="content-section dashboard-feed-panel"><div className="section-heading"><div><p className="eyebrow">Latest canonical jobs</p><h2>What changed recently</h2></div><Link href="/jobs">Explore all jobs →</Link></div>{jobs.kind === "success" ? jobs.value.data.length ? <JobList jobs={jobs.value.data} /> : <EmptyState message="The API has no canonical jobs in this cohort yet." /> : <ApiErrorState error={jobs} />}</section>
    </div>
  </>;
}
