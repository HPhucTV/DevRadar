"use client";

import { useRef, useState } from "react";
import { ApiErrorState } from "@/components/api-state";
import {
  deleteResume,
  generateMatches,
  listMatches,
  MAX_RESUME_BYTES,
  type GenerateMatches,
  type JobMatch,
  type ResumeProfile,
  uploadResume,
} from "@/lib/cv-match";
import type { ApiFailure } from "@/lib/api";

function percent(value: string | number | null): string {
  if (value === null) return "Unavailable";
  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? `${(number * 100).toFixed(1)}%` : "Unavailable";
}

function date(value: string): string {
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function CvMatchPanel() {
  const formRef = useRef<HTMLFormElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [generation, setGeneration] = useState<GenerateMatches | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!file) {
      setError({ kind: "error", status: 422, code: "resume_file_required", message: "Choose a PDF or DOCX resume." });
      return;
    }
    if (file.size > MAX_RESUME_BYTES) {
      setError({ kind: "error", status: 413, code: "resume_upload_too_large", message: "Resume exceeds the 5 MiB upload limit." });
      return;
    }
    setBusy(true);
    const uploaded = await uploadResume(file);
    if (uploaded.kind === "error") {
      setError(uploaded);
      setBusy(false);
      return;
    }
    setProfile(uploaded.value.data);
    setFile(null);
    formRef.current?.reset();
    const generated = await generateMatches(uploaded.value.data.id);
    if (generated.kind === "error") {
      setError(generated);
      setBusy(false);
      return;
    }
    setGeneration(generated.value.data);
    const listed = await listMatches(uploaded.value.data.id);
    if (listed.kind === "error") setError(listed);
    else setMatches(listed.value.data);
    setNotice("Profile created and current matches loaded. The original file is no longer used by this page.");
    setBusy(false);
  }

  async function refreshMatches() {
    if (!profile) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    const generated = await generateMatches(profile.id);
    if (generated.kind === "error") {
      setError(generated);
      setBusy(false);
      return;
    }
    setGeneration(generated.value.data);
    const listed = await listMatches(profile.id);
    if (listed.kind === "error") setError(listed);
    else setMatches(listed.value.data);
    setNotice("Matches refreshed using the current scoring and extraction identities.");
    setBusy(false);
  }

  async function removeProfile() {
    if (!profile || !window.confirm("Delete this local resume profile and its matches?")) return;
    setBusy(true);
    setError(null);
    const removed = await deleteResume(profile.id);
    if (removed.kind === "error") {
      setError(removed);
      setBusy(false);
      return;
    }
    setProfile(null);
    setGeneration(null);
    setMatches([]);
    setNotice("Profile and derived matches deleted.");
    setBusy(false);
  }

  return (
    <>
      <section className="cv-layout" aria-label="Local resume matching">
        <form className="content-section cv-form" onSubmit={submitUpload} ref={formRef}>
          <div className="section-heading"><div><p className="eyebrow">Protected session</p><h2>Start with your account</h2></div><span>Nothing is saved in the browser.</span></div>
          <label>Resume file<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><small className="field-help">PDF or DOCX, maximum 5 MiB. Raw text and the original file are not shown here.</small></label>
          <button type="submit" disabled={busy}>{busy ? "Processing locally..." : "Upload and find matches"}</button>
        </form>
        {profile ? <section className="content-section profile-summary"><div className="section-heading"><div><p className="eyebrow">Ephemeral profile</p><h2>{profile.fileName}</h2></div><span>Expires {date(profile.expiresAt)}</span></div><dl><dt>Status</dt><dd>{profile.extractionStatus} · {profile.sourceFormat}</dd><dt>Skills</dt><dd>{profile.skills.join(", ") || "No accepted skills"}</dd><dt>Roles</dt><dd>{profile.roles.join(", ") || "No accepted roles"}</dd><dt>Locations</dt><dd>{profile.locations.join(", ") || "No location evidence"}</dd></dl><button className="danger-button" type="button" onClick={removeProfile} disabled={busy}>Delete profile and matches</button></section> : <section className="content-section api-state"><strong>Private by default</strong><p>The profile lives for the protected TTL only. Delete it when you are done.</p></section>}
      </section>
      {error ? <ApiErrorState error={error} /> : null}
      {notice ? <p className="status-message" role="status">{notice}</p> : null}
      {generation ? <section className="content-section"><div className="section-heading"><div><p className="eyebrow">Versioned ranking</p><h2>{generation.storedMatches} current matches</h2></div><button type="button" onClick={refreshMatches} disabled={busy}>Refresh matches</button></div><div className="metric-grid"><div className="metric"><span>Scoring</span><strong>{generation.scoringVersion}</strong><small>{generation.createdMatches} new · {generation.reusedMatches} reused</small></div><div className="metric"><span>Available jobs</span><strong>{generation.availableJobs}</strong><small>{generation.unavailableJobs} without compatible vectors</small></div><div className="metric"><span>Considered</span><strong>{generation.consideredJobs}</strong><small>Generated {date(generation.generatedAt)}</small></div></div>{matches.length ? <div className="match-list">{matches.map((match) => <article className="match-card" key={match.id}><div className="section-heading"><div><p className="eyebrow">{match.job.companyName}</p><h3>{match.job.title}</h3><span>{match.job.location || "Location unavailable"}</span></div><strong className="match-score">{percent(match.overallScore)}</strong></div><p className="match-meta">Evidence {percent(match.evidenceCoverage)} · {match.job.status} · {match.scoringVersion}</p><div className="tag-columns"><div><strong>Matched</strong><p>{match.matchedSkills.join(", ") || "No skill match evidence"}</p></div><div><strong>Missing</strong><p>{match.missingSkills.join(", ") || "No missing skill evidence"}</p></div></div><ul className="explanation-list">{match.explanation.map((item) => <li key={item}>{item}</li>)}</ul><a href={match.job.sourceUrl} target="_blank" rel="noreferrer">Open source posting</a></article>)}</div> : <div className="api-state empty-state"><strong>No current matches</strong><p>No active compatible job vectors produced a match for this profile.</p></div>}</section> : null}
    </>
  );
}
