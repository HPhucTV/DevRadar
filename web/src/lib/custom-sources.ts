import type { ApiFailure, ApiResult, DataEnvelope, ListEnvelope } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export type CustomSourceStatus = "draft" | "preview_ready" | "enabled" | "degraded" | "blocked" | "paused" | "retired";
export type CustomParserMode = "auto" | "html" | "json";
export type CustomScheduleKind = "interval" | "daily_at";

export type CustomSource = {
  id: string;
  sourceId: string;
  name: string;
  status: CustomSourceStatus;
  baseUrl: string;
  allowedHosts: string[];
  allowedPathPrefixes: string[];
  parserMode: CustomParserMode;
  parserVersion: string;
  fieldMapping: Record<string, string>;
  scheduleKind: CustomScheduleKind;
  intervalMinutes: number | null;
  dailyAt: string | null;
  timezone: string;
  itemBudget: number;
  byteBudget: number;
  requestsPerMinute: number;
  permissionAcknowledged: boolean;
  blockReason: string | null;
  nextRunAt: string | null;
  lastPreviewAt: string | null;
  createdAt: string | null;
  updatedAt: string | null;
};

export type CustomPreviewCandidate = {
  externalId: string;
  jobUrl: string;
  title: string;
  company: string;
  location: string | null;
  salary: string | null;
  description: string | null;
  postedAt: string | null;
  confidence: number;
  parserVersion: string;
  provenance: { fieldName: string; sourcePath: string; method: string }[];
  warnings: string[];
};

export type CustomPreview = {
  profile: CustomSource;
  finalUrl: string | null;
  redirectChain: string[];
  coverageStatus: "unknown";
  candidates: CustomPreviewCandidate[];
  failures: { code: string; message: string }[];
};

export type CustomCrawlRun = {
  id: string;
  sourceId: string;
  triggerType: string;
  status: string;
  requestedAt: string;
  scheduledFor: string | null;
};

export type CustomSourceInput = {
  name: string;
  base_url: string;
  allowed_hosts?: string[];
  allowed_path_prefixes?: string[];
  parser_mode: CustomParserMode;
  field_mapping: Record<string, string>;
  schedule_kind: CustomScheduleKind;
  interval_minutes: number | null;
  daily_at: string | null;
  timezone: string;
  item_budget: number;
  byte_budget: number;
  requests_per_minute: number;
  permission_acknowledged: true;
};

export type CustomSourcePatch = Partial<Omit<CustomSourceInput, "permission_acknowledged">> & {
  permission_acknowledged?: true;
  status?: "enabled" | "paused";
};

type Data<T> = DataEnvelope<T>;
type List<T> = ListEnvelope<T>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSource(value: unknown): value is CustomSource {
  return isRecord(value)
    && typeof value.id === "string"
    && typeof value.sourceId === "string"
    && typeof value.name === "string"
    && typeof value.status === "string"
    && typeof value.baseUrl === "string"
    && typeof value.parserMode === "string"
    && typeof value.scheduleKind === "string"
    && typeof value.timezone === "string"
    && isRecord(value.fieldMapping)
    && Array.isArray(value.allowedHosts)
    && Array.isArray(value.allowedPathPrefixes);
}

function isData<T>(value: unknown, predicate: (item: unknown) => item is T): value is Data<T> {
  return isRecord(value) && predicate(value.data);
}

function isList<T>(value: unknown, predicate: (item: unknown) => item is T): value is List<T> {
  return isRecord(value) && Array.isArray(value.data) && isRecord(value.pagination) && value.data.every(predicate);
}

function isPreviewEvidence(value: unknown): boolean {
  return isRecord(value)
    && typeof value.fieldName === "string"
    && typeof value.sourcePath === "string"
    && typeof value.method === "string";
}

function isPreviewCandidate(value: unknown): value is CustomPreviewCandidate {
  return isRecord(value)
    && typeof value.externalId === "string"
    && typeof value.jobUrl === "string"
    && typeof value.title === "string"
    && typeof value.company === "string"
    && Array.isArray(value.provenance)
    && value.provenance.every(isPreviewEvidence)
    && Array.isArray(value.warnings)
    && value.warnings.every((warning) => typeof warning === "string");
}

function isPreview(value: unknown): value is CustomPreview {
  return isRecord(value)
    && isSource(value.profile)
    && (value.finalUrl === null || typeof value.finalUrl === "string")
    && Array.isArray(value.redirectChain)
    && value.redirectChain.every((url) => typeof url === "string")
    && value.coverageStatus === "unknown"
    && Array.isArray(value.candidates)
    && value.candidates.every(isPreviewCandidate)
    && Array.isArray(value.failures);
}

function isRun(value: unknown): value is CustomCrawlRun {
  return isRecord(value) && typeof value.id === "string" && typeof value.sourceId === "string" && typeof value.status === "string" && typeof value.requestedAt === "string";
}

function failure(status: number, body: unknown, fallback: string): ApiFailure {
  const error = isRecord(body) && isRecord(body.error) ? body.error : {};
  return {
    kind: "error",
    status,
    code: typeof error.code === "string" ? error.code : "http_error",
    message: typeof error.message === "string" ? error.message : fallback,
  };
}

async function request<T>(path: string, init: RequestInit, validator: (value: unknown) => value is T, fallback: string): Promise<ApiResult<T>> {
  try {
    const response = await sessionFetch(path, {
      ...init,
      headers: { accept: "application/json", ...(init.body ? { "content-type": "application/json" } : {}), ...(init.headers ?? {}) },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body, fallback);
    if (!validator(body)) return failure(response.status, { error: { code: "invalid_contract" } }, "Backend response did not match the custom source contract.");
    return { kind: "success", value: body };
  } catch {
    return failure(503, { error: { code: "backend_unavailable" } }, "DevRadar API is not reachable.");
  }
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `custom-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function listCustomSources(): Promise<ApiResult<List<CustomSource>>> {
  return request("/api/devradar/custom-sources?page=1&pageSize=50", { method: "GET" }, (value): value is List<CustomSource> => isList(value, isSource), "Custom sources could not be loaded.");
}

export function createCustomSource(input: CustomSourceInput): Promise<ApiResult<Data<CustomSource>>> {
  return request("/api/devradar/custom-sources", { method: "POST", body: JSON.stringify(input) }, (value): value is Data<CustomSource> => isData(value, isSource), "Custom source could not be created.");
}

export function updateCustomSource(profileId: string, patch: CustomSourcePatch): Promise<ApiResult<Data<CustomSource>>> {
  return request(`/api/devradar/custom-sources/${encodeURIComponent(profileId)}`, { method: "PATCH", body: JSON.stringify(patch) }, (value): value is Data<CustomSource> => isData(value, isSource), "Custom source could not be updated.");
}

export function retireCustomSource(profileId: string): Promise<ApiResult<undefined>> {
  return request(`/api/devradar/custom-sources/${encodeURIComponent(profileId)}`, { method: "DELETE" }, (value): value is undefined => value === null || value === undefined, "Custom source could not be retired.");
}

export function previewCustomSource(profileId: string): Promise<ApiResult<Data<CustomPreview>>> {
  return request(`/api/devradar/custom-sources/${encodeURIComponent(profileId)}/preview`, { method: "POST" }, (value): value is Data<CustomPreview> => isData(value, isPreview), "Custom source preview could not be completed.");
}

export function requestCustomCrawl(profileId: string): Promise<ApiResult<Data<CustomCrawlRun>>> {
  return request(`/api/devradar/custom-sources/${encodeURIComponent(profileId)}/crawl-runs`, { method: "POST", headers: { "Idempotency-Key": idempotencyKey() } }, (value): value is Data<CustomCrawlRun> => isData(value, isRun), "Custom crawl could not be queued.");
}

export function listCustomCrawlRuns(profileId: string): Promise<ApiResult<List<CustomCrawlRun>>> {
  return request(`/api/devradar/custom-sources/${encodeURIComponent(profileId)}/crawl-runs?page=1&pageSize=20`, { method: "GET" }, (value): value is List<CustomCrawlRun> => isList(value, isRun), "Custom crawl history could not be loaded.");
}
