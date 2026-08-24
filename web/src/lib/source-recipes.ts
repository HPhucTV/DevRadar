import type { ApiFailure, ApiResult, DataEnvelope, ListEnvelope } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export const MAX_SCREENSHOT_DATA_URL_LENGTH = 2_100_000;
const SCREENSHOT_PATTERN = /^data:image\/(?:webp|png);base64,[A-Za-z0-9+/]*={0,2}$/;

export type SourceRecipeStatus =
  | "draft"
  | "previewing"
  | "preview_ready"
  | "enabled"
  | "paused"
  | "blocked"
  | "retired";

export type SourceRecipe = {
  id: string;
  sourceId: string | null;
  name: string;
  status: SourceRecipeStatus;
  listingUrl: string;
  origin: string;
  termsNotice: "not_reviewed" | "no_specific_restriction_found" | "restricted_terms";
  termsNoticeVersion: string;
  termsAcknowledgementRequired: boolean;
  termsAcknowledged: boolean;
  seniorityFilter: string[];
  scheduleKind: "manual" | "every_6_hours" | "daily" | "weekly";
  timezone: string;
  hasMapping: boolean;
  mappingVersion: string | null;
  blockReason: string | null;
};

export type SourceRecipeInput = {
  name: string;
  listingUrl: string;
  seniorityFilter: string[];
  acknowledgedNoticeVersion?: string | null;
  scheduleKind: "manual" | "every_6_hours" | "daily" | "weekly";
  scheduleLocalTime?: string | null;
  scheduleWeekday?: number | null;
  timezone: string;
};

export type PreviewElement = {
  elementId: string;
  tag: string;
  role: string | null;
  textSummary: string;
  bounds: Record<string, number>;
};

export type SourceRecipePreview = {
  id: string;
  recipeId: string;
  status: "pending" | "running" | "succeeded" | "failed";
  candidates: Array<Record<string, unknown>>;
  warnings: Array<Record<string, unknown>>;
  elements: PreviewElement[];
  proposedHosts: string[];
  screenshotDataUrl: string | null;
  errorCode: string | null;
  expiresAt: string;
};

export type SourceRecipeCrawlRun = {
  id: string;
  sourceId: string;
  triggerType: string;
  status: string;
  coverageStatus: string;
  requestedAt: string;
};

export type SourceRecipeMappingInput = {
  cardElementId: string;
  titleElementId: string;
  companyElementId: string;
  locationElementId: string | null;
  jobUrlElementId: string;
  paginationElementId: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isRecipe(value: unknown): value is SourceRecipe {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    (typeof value.sourceId === "string" || value.sourceId === null) &&
    typeof value.name === "string" &&
    typeof value.status === "string" &&
    typeof value.listingUrl === "string" &&
    typeof value.origin === "string" &&
    typeof value.termsNoticeVersion === "string" &&
    Array.isArray(value.seniorityFilter) &&
    typeof value.hasMapping === "boolean"
  );
}

function isElement(value: unknown): value is PreviewElement {
  return (
    isRecord(value) &&
    typeof value.elementId === "string" &&
    typeof value.tag === "string" &&
    typeof value.textSummary === "string" &&
    isRecord(value.bounds)
  );
}

function isPreview(value: unknown): value is SourceRecipePreview {
  if (!isRecord(value) || typeof value.id !== "string" || typeof value.recipeId !== "string") {
    return false;
  }
  const screenshot = value.screenshotDataUrl;
  if (
    screenshot !== null &&
    (typeof screenshot !== "string" ||
      screenshot.length > MAX_SCREENSHOT_DATA_URL_LENGTH ||
      !SCREENSHOT_PATTERN.test(screenshot))
  ) {
    return false;
  }
  return (
    typeof value.status === "string" &&
    Array.isArray(value.candidates) &&
    Array.isArray(value.warnings) &&
    Array.isArray(value.elements) &&
    value.elements.every(isElement) &&
    Array.isArray(value.proposedHosts) &&
    typeof value.expiresAt === "string"
  );
}

function isRun(value: unknown): value is SourceRecipeCrawlRun {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.sourceId === "string" &&
    typeof value.status === "string" &&
    typeof value.requestedAt === "string"
  );
}

function isData<T>(value: unknown, predicate: (item: unknown) => item is T): value is DataEnvelope<T> {
  return isRecord(value) && predicate(value.data);
}

function isList<T>(value: unknown, predicate: (item: unknown) => item is T): value is ListEnvelope<T> {
  return (
    isRecord(value) &&
    Array.isArray(value.data) &&
    value.data.every(predicate) &&
    isRecord(value.pagination)
  );
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

async function request<T>(
  path: string,
  init: RequestInit,
  validator: (value: unknown) => value is T,
  fallback: string,
): Promise<ApiResult<T>> {
  try {
    const response = await sessionFetch(path, {
      ...init,
      headers: {
        accept: "application/json",
        ...(init.body ? { "content-type": "application/json" } : {}),
        ...(init.headers ?? {}),
      },
    });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body, fallback);
    if (!validator(body)) return failure(response.status, null, "Backend response contract is invalid.");
    return { kind: "success", value: body };
  } catch {
    return failure(503, null, "DevRadar API is not reachable.");
  }
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `recipe-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function listSourceRecipes(): Promise<ApiResult<ListEnvelope<SourceRecipe>>> {
  return request(
    "/api/devradar/source-recipes?page=1&pageSize=50",
    { method: "GET" },
    (value): value is ListEnvelope<SourceRecipe> => isList(value, isRecipe),
    "Source recipes could not be loaded.",
  );
}

export function createSourceRecipe(
  input: SourceRecipeInput,
): Promise<ApiResult<DataEnvelope<SourceRecipe>>> {
  return request(
    "/api/devradar/source-recipes",
    { method: "POST", body: JSON.stringify(input) },
    (value): value is DataEnvelope<SourceRecipe> => isData(value, isRecipe),
    "Source recipe could not be created.",
  );
}

export function updateSourceRecipe(
  recipeId: string,
  patch: Partial<SourceRecipeInput> & { status?: "enabled" | "paused" },
): Promise<ApiResult<DataEnvelope<SourceRecipe>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
    (value): value is DataEnvelope<SourceRecipe> => isData(value, isRecipe),
    "Source recipe could not be updated.",
  );
}

export function requestSourcePreview(
  recipeId: string,
): Promise<ApiResult<DataEnvelope<SourceRecipePreview>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/previews`,
    { method: "POST", body: "{}" },
    (value): value is DataEnvelope<SourceRecipePreview> => isData(value, isPreview),
    "Source preview could not be queued.",
  );
}

export function getSourcePreview(
  recipeId: string,
  previewId: string,
): Promise<ApiResult<DataEnvelope<SourceRecipePreview>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/previews/${encodeURIComponent(previewId)}`,
    { method: "GET" },
    (value): value is DataEnvelope<SourceRecipePreview> => isData(value, isPreview),
    "Source preview could not be loaded.",
  );
}

export function saveSourceMapping(
  recipeId: string,
  previewId: string,
  input: SourceRecipeMappingInput,
): Promise<ApiResult<DataEnvelope<SourceRecipePreview>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/previews/${encodeURIComponent(previewId)}/mapping`,
    { method: "POST", body: JSON.stringify(input) },
    (value): value is DataEnvelope<SourceRecipePreview> => isData(value, isPreview),
    "Source mapping could not be saved.",
  );
}

export function requestSourceCrawl(
  recipeId: string,
): Promise<ApiResult<DataEnvelope<SourceRecipeCrawlRun>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/crawl-runs`,
    { method: "POST", body: "{}", headers: { "Idempotency-Key": idempotencyKey() } },
    (value): value is DataEnvelope<SourceRecipeCrawlRun> => isData(value, isRun),
    "Source crawl could not be queued.",
  );
}

export function listSourceCrawls(
  recipeId: string,
): Promise<ApiResult<ListEnvelope<SourceRecipeCrawlRun>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/crawl-runs?page=1&pageSize=20`,
    { method: "GET" },
    (value): value is ListEnvelope<SourceRecipeCrawlRun> => isList(value, isRun),
    "Source crawl history could not be loaded.",
  );
}
