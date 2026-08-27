import type { ApiFailure, ApiResult, DataEnvelope, ListEnvelope } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export const MAX_SCREENSHOT_DATA_URL_LENGTH = 2_100_000;
const SCREENSHOT_PATTERN = /^data:image\/(?:webp|png);base64,[A-Za-z0-9+/]*={0,2}$/;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const DOCUMENT_HASH_PREFIX_PATTERN = /^[0-9a-f]{12}$/i;

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
  recipeCode: string;
  sourceId: string | null;
  name: string;
  status: SourceRecipeStatus;
  listingUrl: string;
  origin: string;
  allowedHosts: string[];
  allowedPathPrefixes: string[];
  seniorityFilter: string[];
  scheduleKind: "manual" | "every_6_hours" | "daily" | "weekly";
  scheduleLocalTime: string | null;
  scheduleWeekday: number | null;
  timezone: string;
  hasMapping: boolean;
  mappingVersion: string | null;
  blockReason: string | null;
  cooldownUntil: string | null;
  nextRunAt: string | null;
  lastUsedAt: string | null;
};

export type SourceRecipePurgeData = {
  recipeId: string;
  sourceId: string | null;
  deleted: Record<string, number>;
};

export type SourceCatalogEntry = {
  name: string;
  origin: string;
  listingHint: string;
};

export type SourceCatalog = {
  schemaVersion: string;
  entries: SourceCatalogEntry[];
};

export type SourceRecipeInput = {
  name: string;
  listingUrl: string;
  seniorityFilter: string[];
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
  candidates: PreviewCandidate[];
  warnings: Array<Record<string, unknown>>;
  elements: PreviewElement[];
  proposedHosts: string[];
  proposedPathPrefixes: string[];
  screenshotDataUrl: string | null;
  errorCode: string | null;
  expiresAt: string;
};

export type PreviewCandidate = {
  externalId: string;
  jobUrl: string;
  title: string;
  company: string;
  location: string | null;
  levelRaw: string | null;
  description: string | null;
  postedAt: string | null;
  confidence: number;
  provenance: Array<{ fieldName: string; sourcePath: string; method: string }>;
  warnings: string[];
  parserVersion: string;
};

export type SourceRecipeCrawlRun = {
  id: string;
  sourceId: string;
  triggerType: string;
  status: string;
  coverageStatus: string;
  requestedAt: string;
};

export type SourceRecipeDocumentImport = {
  sourceId: string;
  crawlRunId: string;
  jobsFound: number;
  jobsNew: number;
  jobsUpdated: number;
  jobsUnchanged: number;
  itemsFilteredOut: number;
  coverage: "incomplete";
  documentHashPrefix: string;
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
    typeof value.recipeCode === "string" &&
    (typeof value.sourceId === "string" || value.sourceId === null) &&
    typeof value.name === "string" &&
    typeof value.status === "string" &&
    typeof value.listingUrl === "string" &&
    typeof value.origin === "string" &&
    Array.isArray(value.allowedHosts) &&
    value.allowedHosts.every((item) => typeof item === "string") &&
    Array.isArray(value.allowedPathPrefixes) &&
    value.allowedPathPrefixes.every((item) => typeof item === "string") &&
    Array.isArray(value.seniorityFilter) &&
    typeof value.hasMapping === "boolean" &&
    (typeof value.cooldownUntil === "string" || value.cooldownUntil === null)
    && (typeof value.lastUsedAt === "string" || value.lastUsedAt === null)
  );
}

function isCatalogEntry(value: unknown): value is SourceCatalogEntry {
  return (
    isRecord(value) &&
    typeof value.name === "string" &&
    typeof value.origin === "string" &&
    typeof value.listingHint === "string"
  );
}

function isCatalog(value: unknown): value is SourceCatalog {
  return (
    isRecord(value) &&
    typeof value.schemaVersion === "string" &&
    Array.isArray(value.entries) &&
    value.entries.every(isCatalogEntry)
  );
}

function isCandidate(value: unknown): value is PreviewCandidate {
  return (
    isRecord(value) &&
    typeof value.externalId === "string" &&
    typeof value.jobUrl === "string" &&
    typeof value.title === "string" &&
    typeof value.company === "string" &&
    typeof value.confidence === "number" &&
    Array.isArray(value.provenance) &&
    Array.isArray(value.warnings)
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
    value.candidates.every(isCandidate) &&
    Array.isArray(value.warnings) &&
    Array.isArray(value.elements) &&
    value.elements.every(isElement) &&
    Array.isArray(value.proposedHosts) &&
    value.proposedHosts.every((item) => typeof item === "string") &&
    Array.isArray(value.proposedPathPrefixes) &&
    value.proposedPathPrefixes.every((item) => typeof item === "string") &&
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

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isDocumentImport(value: unknown): value is SourceRecipeDocumentImport {
  return (
    isRecord(value) &&
    Object.keys(value).length === 9 &&
    typeof value.sourceId === "string" &&
    UUID_PATTERN.test(value.sourceId) &&
    typeof value.crawlRunId === "string" &&
    UUID_PATTERN.test(value.crawlRunId) &&
    isNonNegativeInteger(value.jobsFound) &&
    isNonNegativeInteger(value.jobsNew) &&
    isNonNegativeInteger(value.jobsUpdated) &&
    isNonNegativeInteger(value.jobsUnchanged) &&
    isNonNegativeInteger(value.itemsFilteredOut) &&
    value.coverage === "incomplete" &&
    typeof value.documentHashPrefix === "string" &&
    DOCUMENT_HASH_PREFIX_PATTERN.test(value.documentHashPrefix)
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
        ...(typeof init.body === "string" ? { "content-type": "application/json" } : {}),
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

export function getSourceCatalog(): Promise<ApiResult<DataEnvelope<SourceCatalog>>> {
  return request(
    "/api/devradar/source-catalog",
    { method: "GET" },
    (value): value is DataEnvelope<SourceCatalog> => isData(value, isCatalog),
    "Source catalog could not be loaded.",
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
  patch: Partial<Omit<SourceRecipeInput, "listingUrl">> & {
    allowedHosts?: string[];
    allowedPathPrefixes?: string[];
    status?: "enabled" | "paused";
  },
): Promise<ApiResult<DataEnvelope<SourceRecipe>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}`,
    { method: "PATCH", body: JSON.stringify(patch) },
    (value): value is DataEnvelope<SourceRecipe> => isData(value, isRecipe),
    "Source recipe could not be updated.",
  );
}

export function confirmPreviewRoutes(
  recipeId: string,
  allowedHosts: string[],
  allowedPathPrefixes: string[],
): Promise<ApiResult<DataEnvelope<SourceRecipe>>> {
  return updateSourceRecipe(recipeId, { allowedHosts, allowedPathPrefixes });
}

export async function retireSourceRecipe(recipeId: string): Promise<ApiResult<null>> {
  try {
    const response = await sessionFetch(`/api/devradar/source-recipes/${encodeURIComponent(recipeId)}`, {
      method: "DELETE",
      headers: { accept: "application/json" },
    });
    if (response.status === 204) return { kind: "success", value: null };
    const body: unknown = await response.json().catch(() => null);
    return failure(response.status, body, "Source recipe could not be retired.");
  } catch {
    return failure(503, null, "DevRadar API is not reachable.");
  }
}

export function purgeSourceRecipe(
  recipeId: string,
  confirmationCode: string,
): Promise<ApiResult<DataEnvelope<SourceRecipePurgeData>>> {
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/purge`,
    { method: "POST", body: JSON.stringify({ confirmationCode }) },
    (value): value is DataEnvelope<SourceRecipePurgeData> => {
      if (!isRecord(value) || !isRecord(value.data) || !isRecord(value.data.deleted)) return false;
      return typeof value.data.recipeId === "string" &&
        (typeof value.data.sourceId === "string" || value.data.sourceId === null) &&
        Object.values(value.data.deleted).every(isNonNegativeInteger);
    },
    "Source recipe could not be purged.",
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

export function importSourceDocument(
  recipeId: string,
  file: File,
): Promise<ApiResult<DataEnvelope<SourceRecipeDocumentImport>>> {
  const form = new FormData();
  form.append("file", file, file.name || "jobs-document");
  return request(
    `/api/devradar/source-recipes/${encodeURIComponent(recipeId)}/document-imports`,
    { method: "POST", body: form },
    (value): value is DataEnvelope<SourceRecipeDocumentImport> =>
      isData(value, isDocumentImport),
    "Source document could not be imported.",
  );
}
