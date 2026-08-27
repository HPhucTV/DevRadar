export type Pagination = { page: number; pageSize: number; totalItems: number; totalPages: number };
export type ListEnvelope<T> = { data: T[]; pagination: Pagination };
export type DataEnvelope<T> = { data: T };
export type ApiFailure = { kind: "error"; status: number; code: string; message: string };
export type ApiResult<T> = { kind: "success"; value: T } | ApiFailure;

export type Job = {
  id: string; title: string; companyName: string;
  location: { raw: string | null; city: string | null; workMode: string | null };
  salary: { raw: string | null; min: number | null; max: number | null; currency: string | null; period: string | null };
  levels: string[]; status: string; postedAt: string | null; firstSeenAt: string; lastSeenAt: string;
  source: { id: string; name: string; url: string }; relevanceScore: number | null;
};
export type JobListQuery = {
  page?: string | number;
  pageSize?: number;
  query?: string;
  location?: string;
  sourceId?: string;
};
export type JobDetail = Job & { descriptionText: string | null; currentSnapshot: { id: string; sourceUrl: string; fetchedAt: string; httpStatus: number; contentType: string | null; parseStatus: string } };
export type JobChange = { id: string; jobId: string; crawlRunId: string; changeType: string; fieldName: string; detectedAt: string; oldValue: unknown; newValue: unknown };
export type Source = { id: string; name: string; baseUrl: string; adapterKey: string; approvalStatus: string; healthStatus: string; consecutiveFailures: number; healthReasonCode: string | null; lastCrawledAt: string | null; lastSuccessAt: string | null };
export type CrawlRun = { id: string; sourceId: string; triggerType: string; requestedAt: string; status: string; coverageStatus: string; startedAt: string | null; finishedAt: string | null; counts: { itemsFound: number; itemsNew: number; itemsUpdated: number; itemsMissing: number; itemsRemoved: number; itemsReactivated: number; itemsFailed: number }; healthSignalCode: string | null; error: { code: string; message: string } | null };
export type Skill = { name: string; category: string; jobCount: number; share: number };
export type AnalyticsMeta = { cohortSize: number; analyzedJobs: number; coverage: number; taxonomyVersion: string; extractionSchemaVersion: string };
export type SkillFrequency = ListEnvelope<Skill> & { meta: AnalyticsMeta };
export type TrendBucket = { periodStart: string; denominator: number; analyzedJobs: number; coverage: number; skills: { name: string; jobCount: number; share: number }[] };
export type SkillTrend = { data: TrendBucket[]; meta: AnalyticsMeta & { from: string; to: string; cohort: string; granularity: string } };
export type PrivacyPolicy = {
  policyVersion: "privacy-v2";
  sourceRecipesLocalOnly: true;
  termsWarningOwnerOverride: true;
  accessControlBypassAllowed: false;
  rawCvFileRetained: false;
  resumeProfileTtlHours: 24;
  externalLlmCvJdAllowed: false;
};

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
function isListEnvelope(value: unknown): value is ListEnvelope<unknown> { return isRecord(value) && Array.isArray(value.data) && isRecord(value.pagination); }
function isDataEnvelope(value: unknown): value is DataEnvelope<unknown> { return isRecord(value) && "data" in value; }
function isSkillFrequency(value: unknown): value is SkillFrequency { return isListEnvelope(value) && isRecord((value as Record<string, unknown>).meta) && value.data.every(isRecord); }
function isPrivacyPolicy(value: unknown): value is PrivacyPolicy {
  return isRecord(value)
    && value.policyVersion === "privacy-v2"
    && value.sourceRecipesLocalOnly === true
    && value.termsWarningOwnerOverride === true
    && value.accessControlBypassAllowed === false
    && value.rawCvFileRetained === false
    && value.resumeProfileTtlHours === 24
    && value.externalLlmCvJdAllowed === false;
}
function baseUrl(): string { return process.env.DEVRADAR_API_BASE_URL?.trim() || "http://127.0.0.1:8000"; }
function url(path: string, query?: Record<string, string | number | undefined>): string { const target = new URL(`/api/v1${path}`, baseUrl()); for (const [key, value] of Object.entries(query ?? {})) if (value !== undefined) target.searchParams.set(key, String(value)); return target.toString(); }

async function request<T>(path: string, query: Record<string, string | number | undefined> | undefined, validator: (value: unknown) => value is T): Promise<ApiResult<T>> {
  try {
    const response = await fetch(url(path, query), { cache: "no-store", headers: { accept: "application/json" } });
    let body: unknown;
    try { body = await response.json(); } catch { return { kind: "error", status: response.status, code: "invalid_json", message: "Backend returned an invalid response." }; }
    if (!response.ok) { const error = isRecord(body) && isRecord(body.error) ? body.error : {}; return { kind: "error", status: response.status, code: typeof error.code === "string" ? error.code : "http_error", message: typeof error.message === "string" ? error.message : "Backend request failed." }; }
    if (!validator(body)) return { kind: "error", status: response.status, code: "invalid_contract", message: "Backend response did not match the documented contract." };
    return { kind: "success", value: body };
  } catch { return { kind: "error", status: 503, code: "backend_unavailable", message: "DevRadar API is not reachable." }; }
}
export function listJobs(query: JobListQuery = {}): Promise<ApiResult<ListEnvelope<Job>>> { return request("/jobs", { ...query }, (value): value is ListEnvelope<Job> => isListEnvelope(value) && value.data.every(isRecord)); }
export function getJob(jobId: string): Promise<ApiResult<DataEnvelope<JobDetail>>> { return request(`/jobs/${encodeURIComponent(jobId)}`, undefined, (value): value is DataEnvelope<JobDetail> => isDataEnvelope(value) && isRecord(value.data)); }
export function listJobChanges(jobId: string): Promise<ApiResult<ListEnvelope<JobChange>>> { return request(`/jobs/${encodeURIComponent(jobId)}/changes`, { page: 1, pageSize: 20 }, (value): value is ListEnvelope<JobChange> => isListEnvelope(value) && value.data.every(isRecord)); }
export function listSources(): Promise<ApiResult<ListEnvelope<Source>>> { return request("/sources", { page: 1, pageSize: 100 }, (value): value is ListEnvelope<Source> => isListEnvelope(value) && value.data.every(isRecord)); }
export function listCrawlRuns(): Promise<ApiResult<ListEnvelope<CrawlRun>>> { return request("/crawl-runs", { page: 1, pageSize: 20 }, (value): value is ListEnvelope<CrawlRun> => isListEnvelope(value) && value.data.every(isRecord)); }
export function listSkills(): Promise<ApiResult<SkillFrequency>> { return request("/skills", { page: 1, pageSize: 12 }, isSkillFrequency); }
export function listSkillTrends(from: string, to: string): Promise<ApiResult<SkillTrend>> { return request("/skill-trends", { from, to, granularity: "month", topSkills: 8 }, (value): value is SkillTrend => isRecord(value) && Array.isArray(value.data) && isRecord(value.meta)); }
export function getPrivacy(): Promise<ApiResult<DataEnvelope<PrivacyPolicy>>> { return request("/privacy", undefined, (value): value is DataEnvelope<PrivacyPolicy> => isDataEnvelope(value) && isPrivacyPolicy(value.data)); }
