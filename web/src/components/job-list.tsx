import Link from "next/link";
import type { Job } from "@/lib/api";

function date(value: string) { return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(new Date(value)); }
function salary(job: Job) { return job.salary.raw ?? "Salary not disclosed"; }
export function JobList({ jobs }: { jobs: Job[] }) { return <div className="job-list">{jobs.map((job) => <article className="job-card" key={job.id}><div className="job-card-main"><p className="eyebrow"><span className="source-badge">{job.source.name}</span> · {date(job.lastSeenAt)}</p><h2><Link href={`/jobs/${job.id}`}>{job.title}</Link></h2><p>{job.companyName} · {job.location.city ?? job.location.raw ?? "Location not disclosed"}</p></div><div className="job-card-meta"><span className="salary-badge">{salary(job)}</span><div className="level-list" aria-label="Job levels">{job.levels.length ? job.levels.map((level) => <span className="level-badge" key={level}>{level}</span>) : <span className="level-badge">Level not disclosed</span>}</div></div></article>)}</div>; }
