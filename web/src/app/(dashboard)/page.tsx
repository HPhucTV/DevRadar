import Link from "next/link";
import { ApiErrorState, EmptyState, Metric } from "@/components/api-state";
import { JobList } from "@/components/job-list";
import { listJobs, listSkills, listSources } from "@/lib/api";

export const dynamic = "force-dynamic";
export default async function OverviewPage() {
  const [jobs, sources, skills] = await Promise.all([listJobs({ pageSize: 5 }), listSources(), listSkills()]);
  return <><section className="page-intro"><p className="eyebrow">Current inventory</p><h1>Make the market legible.</h1><p>Overview uses the approved-source catalog and canonical API responses. Cohort and coverage stay visible when analytics arrives.</p></section><div className="metric-grid">{sources.kind === "success" ? <Metric label="Approved sources" value={sources.value.data.filter((item) => item.approvalStatus === "approved").length} /> : <Metric label="Sources" value="—" note="Unavailable" />}{skills.kind === "success" ? <Metric label="Tracked skills" value={skills.value.pagination.totalItems} note={`Coverage ${(skills.value.meta.coverage * 100).toFixed(1)}%`} /> : <Metric label="Skills" value="—" note="Unavailable" />}{jobs.kind === "success" ? <Metric label="Visible jobs" value={jobs.value.pagination.totalItems} /> : <Metric label="Jobs" value="—" note="Unavailable" />}</div><section className="content-section"><div className="section-heading"><div><p className="eyebrow">Latest canonical jobs</p><h2>What changed recently</h2></div><Link href="/jobs">Explore all jobs →</Link></div>{jobs.kind === "success" ? jobs.value.data.length ? <JobList jobs={jobs.value.data} /> : <EmptyState message="The API has no canonical jobs in this cohort yet." /> : <ApiErrorState error={jobs} />}</section></>;
}
