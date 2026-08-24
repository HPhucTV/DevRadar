import { ApiErrorState, EmptyState } from "@/components/api-state";
import { JobList } from "@/components/job-list";
import { formatNumber } from "@/i18n/locale";
import { getI18n } from "@/i18n/server";
import { listJobs } from "@/lib/api";

export const dynamic = "force-dynamic";
type SearchParams = Promise<Record<string, string | string[] | undefined>>;
function first(value: string | string[] | undefined) { return Array.isArray(value) ? value[0] : value; }
export default async function JobsPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams; const query = first(params.query); const location = first(params.location); const page = first(params.page);
  const [{ locale, dictionary }, result] = await Promise.all([getI18n(), listJobs({ page: page && /^\d+$/.test(page) ? page : 1, pageSize: 20, query: query?.trim() || undefined, location: location?.trim() || undefined })]);
  return <><section className="page-intro"><p className="eyebrow">{dictionary.jobs.eyebrow}</p><h1>{dictionary.jobs.title}</h1><p>{dictionary.jobs.body}</p></section><form className="jobs-toolbar filter-form" action="/jobs"><label>{dictionary.jobs.keyword}<span className="input-shell"><input name="query" defaultValue={query} placeholder={dictionary.jobs.keywordPlaceholder} /></span></label><label>{dictionary.jobs.location}<span className="input-shell"><input name="location" defaultValue={location} placeholder={dictionary.jobs.locationPlaceholder} /></span></label><button className="button-primary" type="submit">{dictionary.jobs.filter}</button></form><section className="content-section">{result.kind === "success" ? result.value.data.length ? <><div className="section-heading"><h2>{formatNumber(result.value.pagination.totalItems, locale)} {dictionary.jobs.result}</h2><span>{dictionary.common.page} {formatNumber(result.value.pagination.page, locale)} {dictionary.common.of} {formatNumber(result.value.pagination.totalPages || 1, locale)}</span></div><JobList jobs={result.value.data} /></> : <EmptyState message={dictionary.jobs.noResult} /> : <ApiErrorState error={result} />}</section></>;
}
