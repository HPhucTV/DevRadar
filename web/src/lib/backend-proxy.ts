import { bffRateLimit } from "@/lib/bff-rate-limit";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
export const MAX_PROXY_BODY_BYTES = 6 * 1024 * 1024;
const MAX_PROXY_RESPONSE_BYTES = 3 * 1024 * 1024;
const BACKEND_TIMEOUT_MS = 10_000;

function backendUrl(path: string): string {
  const base = process.env.DEVRADAR_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  return new URL(`/api/v1${path}`, base).toString();
}

function forwardedHeaders(request: Request, init: RequestInit): Headers {
  const headers = new Headers({ accept: "application/json" });
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const csrf = request.headers.get("x-devradar-csrf");
  if (csrf) headers.set("x-devradar-csrf", csrf);
  const origin = request.headers.get("origin");
  if (origin) headers.set("origin", origin);
  for (const [key, value] of new Headers(init.headers).entries()) headers.set(key, value);
  if (typeof init.body === "string" && !headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  return headers;
}

export async function proxyBackend(
  request: Request,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const limited = bffRateLimit(request, path);
  if (limited) return limited;
  if (typeof init.body === "string" && new TextEncoder().encode(init.body).byteLength > MAX_PROXY_BODY_BYTES) {
    return Response.json(
      { error: { code: "proxy_body_too_large", message: "Request body exceeds the proxy limit." } },
      { status: 413 },
    );
  }
  try {
    const response = await fetch(backendUrl(path), {
      ...init,
      headers: forwardedHeaders(request, init),
      cache: "no-store",
      signal: AbortSignal.timeout(BACKEND_TIMEOUT_MS),
    });
    const headers = new Headers();
    const contentType = response.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
    const requestId = response.headers.get("x-request-id");
    if (requestId) headers.set("x-request-id", requestId);
    const setCookie = (response.headers as Headers & { getSetCookie?: () => string[] }).getSetCookie?.();
    if (setCookie?.length) {
      for (const cookie of setCookie) headers.append("set-cookie", cookie);
    }
    else {
      const fallbackCookie = response.headers.get("set-cookie");
      if (fallbackCookie) headers.set("set-cookie", fallbackCookie);
    }
    const body = response.status === 204 || response.status === 304 ? null : await boundedBody(response);
    return new Response(body, { status: response.status, headers });
  } catch {
    return Response.json(
      { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } },
      { status: 503 },
    );
  }
}

async function boundedBody(response: Response): Promise<ArrayBuffer> {
  const contentLength = Number(response.headers.get("content-length") ?? "0");
  if (contentLength > MAX_PROXY_RESPONSE_BYTES) throw new Error("proxy response too large");
  if (!response.body) return new ArrayBuffer(0);
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  try {
    while (true) {
      const next = await reader.read();
      if (next.done) break;
      total += next.value.byteLength;
      if (total > MAX_PROXY_RESPONSE_BYTES) throw new Error("proxy response too large");
      chunks.push(next.value);
    }
  } finally {
    reader.releaseLock();
  }
  const result = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    result.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return result.buffer;
}

export function invalidUpload(message: string, status = 422): Response {
  return Response.json({ error: { code: "resume_multipart_invalid", message } }, { status });
}
