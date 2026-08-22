import type { ApiFailure, ApiResult } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export const MAX_RESUME_BYTES = 5 * 1024 * 1024;

export type ResumeProfile = {
  id: string;
  fileName: string;
  sourceFormat: string;
  parserVersion: string;
  extractionStatus: string;
  skills: string[];
  roles: string[];
  locations: string[];
  experienceYears: string | null;
  retentionMode: string;
  createdAt: string;
  expiresAt: string;
};

export type GenerateMatches = {
  profileId: string;
  scoringVersion: string;
  consideredJobs: number;
  availableJobs: number;
  unavailableJobs: number;
  storedMatches: number;
  createdMatches: number;
  reusedMatches: number;
  generatedAt: string;
};

export type JobMatch = {
  id: string;
  jobId: string;
  overallScore: string | number;
  evidenceCoverage: string | number;
  components: {
    skill: string | number | null;
    semantic: string | number | null;
    experience: string | number | null;
    location: string | number | null;
    role: string | number | null;
  };
  matchedSkills: string[];
  missingSkills: string[];
  explanation: string[];
  scoringVersion: string;
  embeddingModel: string;
  embeddingRevision: string;
  createdAt: string;
  job: {
    title: string;
    companyName: string;
    location: string | null;
    levels: string[];
    status: string;
    sourceUrl: string;
  };
};

export type Pagination = {
  page: number;
  pageSize: number;
  totalItems: number;
  totalPages: number;
};

type DataEnvelope<T> = { data: T };
type ListEnvelope<T> = { data: T[]; pagination: Pagination };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isDataEnvelope(value: unknown): value is DataEnvelope<unknown> {
  return isRecord(value) && "data" in value;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isProfile(value: unknown): value is ResumeProfile {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.fileName === "string" &&
    typeof value.sourceFormat === "string" &&
    typeof value.parserVersion === "string" &&
    typeof value.extractionStatus === "string" &&
    isStringArray(value.skills) &&
    isStringArray(value.roles) &&
    isStringArray(value.locations) &&
    (typeof value.experienceYears === "string" || value.experienceYears === null) &&
    typeof value.retentionMode === "string" &&
    typeof value.createdAt === "string" &&
    typeof value.expiresAt === "string"
  );
}

function isGenerateMatches(value: unknown): value is GenerateMatches {
  return (
    isRecord(value) &&
    typeof value.profileId === "string" &&
    typeof value.scoringVersion === "string" &&
    ["consideredJobs", "availableJobs", "unavailableJobs", "storedMatches", "createdMatches", "reusedMatches"].every(
      (field) => typeof value[field] === "number",
    ) &&
    typeof value.generatedAt === "string"
  );
}

function isMatch(value: unknown): value is JobMatch {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.jobId === "string" &&
    (typeof value.overallScore === "number" || typeof value.overallScore === "string") &&
    (typeof value.evidenceCoverage === "number" || typeof value.evidenceCoverage === "string") &&
    isRecord(value.components) &&
    isStringArray(value.matchedSkills) &&
    isStringArray(value.missingSkills) &&
    isStringArray(value.explanation) &&
    typeof value.scoringVersion === "string" &&
    typeof value.embeddingModel === "string" &&
    typeof value.embeddingRevision === "string" &&
    typeof value.createdAt === "string" &&
    isRecord(value.job) &&
    typeof value.job.title === "string" &&
    typeof value.job.companyName === "string" &&
    (typeof value.job.location === "string" || value.job.location === null) &&
    isStringArray(value.job.levels) &&
    typeof value.job.status === "string" &&
    typeof value.job.sourceUrl === "string"
  );
}

function isPagination(value: unknown): value is Pagination {
  return (
    isRecord(value) &&
    ["page", "pageSize", "totalItems", "totalPages"].every((field) => typeof value[field] === "number")
  );
}

function isProfileResponse(value: unknown): value is DataEnvelope<ResumeProfile> {
  return isDataEnvelope(value) && isProfile(value.data);
}

function isGenerateResponse(value: unknown): value is DataEnvelope<GenerateMatches> {
  return isDataEnvelope(value) && isGenerateMatches(value.data);
}

function isMatchesResponse(value: unknown): value is ListEnvelope<JobMatch> {
  return isRecord(value) && Array.isArray(value.data) && value.data.every(isMatch) && isPagination(value.pagination);
}

function errorFromBody(status: number, body: unknown): ApiFailure {
  const error = isRecord(body) && isRecord(body.error) ? body.error : {};
  return {
    kind: "error",
    status,
    code: typeof error.code === "string" ? error.code : "http_error",
    message: typeof error.message === "string" ? error.message : "Backend request failed.",
  };
}

async function request<T>(
  path: string,
  options: RequestInit,
  validator: (value: unknown) => value is T,
): Promise<ApiResult<T>> {
  try {
    const response = await sessionFetch(path, options);
    let body: unknown;
    try {
      body = await response.json();
    } catch {
      return { kind: "error", status: response.status, code: "invalid_json", message: "Backend returned an invalid response." };
    }
    if (!response.ok) return errorFromBody(response.status, body);
    if (!validator(body)) return { kind: "error", status: response.status, code: "invalid_contract", message: "Backend response did not match the documented contract." };
    return { kind: "success", value: body };
  } catch {
    return { kind: "error", status: 503, code: "backend_unavailable", message: "DevRadar API is not reachable." };
  }
}

export function uploadResume(file: File): Promise<ApiResult<DataEnvelope<ResumeProfile>>> {
  const form = new FormData();
  form.append("file", file, file.name);
  return request("/api/devradar/resume-profiles", { method: "POST", body: form }, isProfileResponse);
}

export function generateMatches(profileId: string): Promise<ApiResult<DataEnvelope<GenerateMatches>>> {
  return request(`/api/devradar/resume-profiles/${encodeURIComponent(profileId)}/matches`, { method: "POST" }, isGenerateResponse);
}

export function listMatches(profileId: string): Promise<ApiResult<ListEnvelope<JobMatch>>> {
  return request(`/api/devradar/resume-profiles/${encodeURIComponent(profileId)}/matches?page=1&pageSize=20`, {}, isMatchesResponse);
}

export async function deleteResume(profileId: string): Promise<ApiResult<null>> {
  try {
    const response = await sessionFetch(`/api/devradar/resume-profiles/${encodeURIComponent(profileId)}`, { method: "DELETE" });
    if (!response.ok) {
      let body: unknown = {};
      try { body = await response.json(); } catch { /* safe generic error below */ }
      return errorFromBody(response.status, body);
    }
    return { kind: "success", value: null };
  } catch {
    return { kind: "error", status: 503, code: "backend_unavailable", message: "DevRadar API is not reachable." };
  }
}
