import type { ApiFailure, ApiResult, ListEnvelope } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export type AlertRule = {
  id: string;
  name: string;
  companyQuery: string | null;
  skillQuery: string | null;
  resumeProfileId: string | null;
  minMatchScore: string | null;
  channel: "discord";
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
};

export type AlertDispatch = {
  ruleId: string;
  consideredJobs: number;
  createdDeliveries: number;
  sentDeliveries: number;
  skippedDeliveries: number;
  failedDeliveries: number;
};

type DataEnvelope<T> = { data: T };
type AlertList = ListEnvelope<AlertRule>;

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
function isAlertRule(value: unknown): value is AlertRule { return isRecord(value) && typeof value.id === "string" && typeof value.name === "string" && value.channel === "discord"; }
function isAlertList(value: unknown): value is AlertList { return isRecord(value) && Array.isArray(value.data) && isRecord(value.pagination) && value.data.every(isAlertRule); }
function isDispatch(value: unknown): value is AlertDispatch { return isRecord(value) && typeof value.ruleId === "string" && typeof value.sentDeliveries === "number"; }
function failure(status: number, body: unknown): ApiFailure { const error = isRecord(body) && isRecord(body.error) ? body.error : {}; return { kind: "error", status, code: typeof error.code === "string" ? error.code : "http_error", message: typeof error.message === "string" ? error.message : "Alert request failed." }; }

async function request<T>(path: string, init: RequestInit, validator: (value: unknown) => value is T): Promise<ApiResult<T>> {
  try {
    const response = await sessionFetch(path, { ...init, headers: { "content-type": "application/json", ...(init.headers ?? {}) } });
    if (response.status === 204) return { kind: "success", value: undefined as T };
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body);
    return validator(body) ? { kind: "success", value: body } : failure(response.status, { error: { code: "invalid_contract", message: "Backend response did not match the alert contract." } });
  } catch { return failure(503, { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } }); }
}

export function listAlertRules(): Promise<ApiResult<AlertList>> { return request("/api/devradar/alert-rules?page=1&pageSize=20", { method: "GET" }, isAlertList); }
export function createAlertRule(input: { name: string; companyQuery?: string; skillQuery?: string; enabled: boolean }): Promise<ApiResult<DataEnvelope<AlertRule>>> { return request("/api/devradar/alert-rules", { method: "POST", body: JSON.stringify({ ...input, channel: "discord" }) }, (value): value is DataEnvelope<AlertRule> => isRecord(value) && isAlertRule(value.data)); }
export function setAlertRuleEnabled(ruleId: string, enabled: boolean): Promise<ApiResult<DataEnvelope<AlertRule>>> { return request(`/api/devradar/alert-rules/${encodeURIComponent(ruleId)}`, { method: "PATCH", body: JSON.stringify({ enabled }) }, (value): value is DataEnvelope<AlertRule> => isRecord(value) && isAlertRule(value.data)); }
export function deleteAlertRule(ruleId: string): Promise<ApiResult<undefined>> { return request(`/api/devradar/alert-rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" }, (value): value is undefined => value === undefined); }
export function dispatchAlertRule(ruleId: string): Promise<ApiResult<DataEnvelope<AlertDispatch>>> { return request(`/api/devradar/alert-rules/${encodeURIComponent(ruleId)}/dispatch?maxItems=5`, { method: "POST" }, (value): value is DataEnvelope<AlertDispatch> => isRecord(value) && isDispatch(value.data)); }
