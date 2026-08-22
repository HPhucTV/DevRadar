import Link from "next/link";
import type { Job } from "@/lib/api";

function date(value: string) { return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium" }).format(new Date(value)); }
function salary(job: Job) { return job.salary.raw ?? "Salary not disclosed"; }
export function JobList({ jobs }: { jobs: Job[] }) { return <div className="job-list">{jobs.map((job) => <article className="job-row" key={job.id}><div><p className="eyebrow">{job.source.name} · {date(job.lastSeenAt)}</p><h2><Link href={`/jobs/${job.id}`}>{job.title}</Link></h2><p>{job.companyName} · {job.location.city ?? job.location.raw ?? "Location not disclosed"}</p></div><div className="job-meta"><span>{salary(job)}</span><span>{job.levels.join(" · ") || "Level not disclosed"}</span></div></article>)}</div>; }
