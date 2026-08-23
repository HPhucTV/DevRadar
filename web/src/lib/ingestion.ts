import type { ApiFailure, ApiResult, CrawlRun, DataEnvelope, ListEnvelope, Source } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export type IngestionSource = Source;
export type IngestionRun = CrawlRun;

type SourceList = ListEnvelope<IngestionSource>;
type RunList = ListEnvelope<IngestionRun>;
type RunResponse = DataEnvelope<IngestionRun>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isListEnvelope(value: unknown): value is ListEnvelope<unknown> {
  return isRecord(value) && Array.isArray(value.data) && isRecord(value.pagination);
}

function isSource(value: unknown): value is IngestionSource {
  return isRecord(value) && typeof value.id === "string" && typeof value.name === "string" && typeof value.approvalStatus === "string";
}

function isRun(value: unknown): value is IngestionRun {
  return isRecord(value) && typeof value.id === "string" && typeof value.sourceId === "string" && typeof value.status === "string";
}

function failure(status: number, body: unknown): ApiFailure {
  const error = isRecord(body) && isRecord(body.error) ? body.error : {};
  return {
    kind: "error",
    status,
    code: typeof error.code === "string" ? error.code : "http_error",
    message: typeof error.message === "string" ? error.message : "Ingestion request failed.",
  };
}

async function request<T>(path: string, init: RequestInit, validator: (value: unknown) => value is T): Promise<ApiResult<T>> {
  try {
    const response = await sessionFetch(path, {
      ...init,
      headers: { accept: "application/json", ...(init.body ? { "content-type": "application/json" } : {}), ...(init.headers ?? {}) },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body);
    return validator(body) ? { kind: "success", value: body } : failure(response.status, { error: { code: "invalid_contract", message: "Backend response did not match the ingestion contract." } });
  } catch {
    return failure(503, { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } });
  }
}

function isSourceList(value: unknown): value is SourceList {
  return isListEnvelope(value) && value.data.every(isSource);
}

function isRunList(value: unknown): value is RunList {
  return isListEnvelope(value) && value.data.every(isRun);
}

function isRunResponse(value: unknown): value is RunResponse {
  return isRecord(value) && isRun(value.data);
}

export function listIngestionSources(): Promise<ApiResult<SourceList>> {
  return request("/api/devradar/sources?page=1&pageSize=100", { method: "GET" }, isSourceList);
}

export function listIngestionRuns(): Promise<ApiResult<RunList>> {
  return request("/api/devradar/crawl-runs?page=1&pageSize=20", { method: "GET" }, isRunList);
}

export function getIngestionRun(runId: string): Promise<ApiResult<RunResponse>> {
  return request(`/api/devradar/crawl-runs/${encodeURIComponent(runId)}`, { method: "GET" }, isRunResponse);
}

export function requestCrawlRun(sourceId: string, idempotencyKey: string): Promise<ApiResult<RunResponse>> {
  return request("/api/devradar/crawl-runs", {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ sourceId }),
  }, isRunResponse);
}
