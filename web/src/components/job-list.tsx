import Link from "next/link";
import { formatDate } from "@/i18n/locale";
import { getI18n } from "@/i18n/server";
import type { Job } from "@/lib/api";

export async function JobList({ jobs }: { jobs: Job[] }) { const { locale, dictionary } = await getI18n(); return <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-card-main"><p className="eyebrow"><span className="source-badge">{job.source.name}</span> · {formatDate(job.lastSeenAt, locale, { dateStyle: "medium" })}</p><h2><Link href={`/jobs/${job.id}`}>{job.title}</Link></h2><p>{job.companyName} · {job.location.city ?? job.location.raw ?? dictionary.jobs.locationMissing}</p></div><div className="job-card-meta"><span className="salary-badge">{job.salary.raw ?? dictionary.jobs.salaryMissing}</span><div className="level-list" aria-label={dictionary.jobs.levelsLabel}>{job.levels.length ? job.levels.map((level) => <span className="level-badge" key={level}>{level}</span>) : <span className="level-badge">{dictionary.jobs.levelMissing}</span>}</div></div></article>)}</div>; }
