import { ApiErrorState, EmptyState } from "@/components/api-state";
import { JobList } from "@/components/job-list";
import { listJobs } from "@/lib/api";

export const dynamic = "force-dynamic";
type SearchParams = Promise<Record<string, string | string[] | undefined>>;
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
export default async function JobsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams; const query = first(params.query); const location = first(params.location); const page = first(params.page);
  const result = await listJobs({ page: page && /^\d+$/.test(page) ? page : 1, pageSize: 20, query: query?.trim() || undefined, location: location?.trim() || undefined });
  return <><section className="page-intro"><p className="eyebrow">Canonical explorer</p><h1>Jobs worth a closer look.</h1><p>Search stays literal and source-scoped. Semantic ranking remains available through the API contract and will be surfaced after the view baseline is stable.</p></section><form className="filter-form" action="/jobs"><label>Keyword<input name="query" defaultValue={query} placeholder="e.g. Python, backend" /></label><label>Location<input name="location" defaultValue={location} placeholder="e.g. Ho Chi Minh" /></label><button type="submit">Filter jobs</button></form><section className="content-section">{result.kind === "success" ? result.value.data.length ? <><div className="section-heading"><h2>{result.value.pagination.totalItems} jobs in the current result</h2><span>Page {result.value.pagination.page} / {result.value.pagination.totalPages || 1}</span></div><JobList jobs={result.value.data} /></> : <EmptyState message="No jobs match these filters. Try a broader literal search." /> : <ApiErrorState error={result} />}</section></>;
}
