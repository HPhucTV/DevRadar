"use client";

import { useRef, useState } from "react";
import { ApiErrorState } from "@/components/api-state";
import type { Dictionary } from "@/i18n/dictionaries";
import { useI18n } from "@/i18n/locale-provider";
import { formatDate, formatNumber, formatPercent, type Locale } from "@/i18n/locale";
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

type Notice = (dictionary: Dictionary, locale: Locale) => string;

export function CvMatchPanel() {
  const { locale, dictionary } = useI18n();
  const statusLabels = dictionary.status as Record<string, string>;
  const formRef = useRef<HTMLFormElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [profile, setProfile] = useState<ResumeProfile | null>(null);
  const [generation, setGeneration] = useState<GenerateMatches | null>(null);
  const [matches, setMatches] = useState<JobMatch[]>([]);
  const [error, setError] = useState<ApiFailure | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);

  async function submitUpload(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setNotice(null);
    if (!file) {
      setError({ kind: "error", status: 422, code: "resume_file_required", message: dictionary.errors.codes.resume_file_required });
      return;
    }
    if (file.size > MAX_RESUME_BYTES) {
      setError({ kind: "error", status: 413, code: "resume_upload_too_large", message: dictionary.errors.codes.resume_upload_too_large });
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
    setNotice(() => (messages: Dictionary) => messages.cv.profileCreated);
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
    setNotice(() => (messages: Dictionary) => messages.cv.matchesRefreshed);
    setBusy(false);
  }

  async function removeProfile() {
    if (!profile || !window.confirm(dictionary.cv.deleteConfirm)) return;
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
    setNotice(() => (messages: Dictionary) => messages.cv.deleted);
    setBusy(false);
  }

  return (
    <div className="workflow-layout">
      <section className="cv-layout workflow-panel" aria-label={dictionary.cv.ariaLabel}>
        <form className="content-section cv-form cv-upload-card" onSubmit={submitUpload} ref={formRef}>
          <div className="section-heading"><div><p className="eyebrow">{dictionary.cv.sessionEyebrow}</p><h2>{dictionary.cv.startTitle}</h2></div><span>{dictionary.cv.browserNote}</span></div>
          <label className="upload-dropzone">{dictionary.cv.file}<input type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><small className="field-help">{dictionary.cv.fileHelp}</small></label>
          <button className="button-primary" type="submit" disabled={busy}>{busy ? dictionary.cv.processing : dictionary.cv.upload}</button>
        </form>
        {profile ? <section className="content-section profile-summary profile-card"><div className="section-heading"><div><p className="eyebrow">{dictionary.cv.profileEyebrow}</p><h2>{profile.fileName}</h2></div><span>{dictionary.cv.expires} {formatDate(profile.expiresAt, locale)}</span></div><dl><dt>{dictionary.cv.status}</dt><dd>{statusLabels[profile.extractionStatus] ?? profile.extractionStatus} · {profile.sourceFormat}</dd><dt>{dictionary.cv.skills}</dt><dd>{profile.skills.join(", ") || dictionary.cv.noSkills}</dd><dt>{dictionary.cv.roles}</dt><dd>{profile.roles.join(", ") || dictionary.cv.noRoles}</dd><dt>{dictionary.cv.locations}</dt><dd>{profile.locations.join(", ") || dictionary.cv.noLocations}</dd></dl><button className="danger-button" type="button" onClick={removeProfile} disabled={busy}>{dictionary.cv.deleteProfile}</button></section> : <section className="content-section api-state privacy-note"><strong>{dictionary.cv.privateTitle}</strong><p>{dictionary.cv.privateBody}</p></section>}
      </section>
      {error ? <ApiErrorState error={error} /> : null}
      {notice ? <p className="status-message" role="status">{notice(dictionary, locale)}</p> : null}
      {generation ? <section className="content-section match-results"><div className="section-heading"><div><p className="eyebrow">{dictionary.cv.rankingEyebrow}</p><h2>{formatNumber(generation.storedMatches, locale)} {dictionary.cv.currentMatches}</h2></div><button type="button" onClick={refreshMatches} disabled={busy}>{dictionary.cv.refreshMatches}</button></div><div className="metric-grid"><div className="metric"><span>{dictionary.cv.scoring}</span><strong>{generation.scoringVersion}</strong><small>{formatNumber(generation.createdMatches, locale)} {dictionary.cv.new} · {formatNumber(generation.reusedMatches, locale)} {dictionary.cv.reused}</small></div><div className="metric"><span>{dictionary.cv.availableJobs}</span><strong>{formatNumber(generation.availableJobs, locale)}</strong><small>{formatNumber(generation.unavailableJobs, locale)} {dictionary.cv.withoutVectors}</small></div><div className="metric"><span>{dictionary.cv.considered}</span><strong>{formatNumber(generation.consideredJobs, locale)}</strong><small>{dictionary.cv.generated} {formatDate(generation.generatedAt, locale)}</small></div></div>{matches.length ? <div className="match-list">{matches.map((match) => { const score = Number(match.overallScore); const evidence = Number(match.evidenceCoverage); return <article className="match-card" key={match.id}><div className="section-heading"><div><p className="eyebrow">{match.job.companyName}</p><h3>{match.job.title}</h3><span>{match.job.location || dictionary.cv.locationMissing}</span></div><strong className="match-score score-tile">{Number.isFinite(score) ? formatPercent(score, locale) : dictionary.cv.percentUnavailable}</strong></div><p className="match-meta evidence-meta">{dictionary.cv.evidence} {Number.isFinite(evidence) ? formatPercent(evidence, locale) : dictionary.cv.percentUnavailable} · {statusLabels[match.job.status] ?? match.job.status} · {match.scoringVersion}</p><div className="tag-columns skill-columns"><div className="matched-skills"><strong>{dictionary.cv.matched}</strong><p>{match.matchedSkills.join(", ") || dictionary.cv.noMatchedSkills}</p></div><div className="missing-skills"><strong>{dictionary.cv.missing}</strong><p>{match.missingSkills.join(", ") || dictionary.cv.noMissingSkills}</p></div></div><ul className="explanation-list">{match.explanation.map((item) => <li key={item}>{item}</li>)}</ul><a href={match.job.sourceUrl} target="_blank" rel="noreferrer">{dictionary.cv.openSource}</a></article>; })}</div> : <div className="api-state empty-state"><strong>{dictionary.cv.noMatchesTitle}</strong><p>{dictionary.cv.noMatchesBody}</p></div>}</section> : null}
    </div>
  );
}
