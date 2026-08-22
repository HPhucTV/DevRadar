const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

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
  return headers;
}

export async function proxyBackend(
  request: Request,
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  try {
    const response = await fetch(backendUrl(path), {
      ...init,
      headers: forwardedHeaders(request, init),
      cache: "no-store",
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
    const body = response.status === 204 || response.status === 304 ? null : await response.arrayBuffer();
    return new Response(body, { status: response.status, headers });
  } catch {
    return Response.json(
      { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } },
      { status: 503 },
    );
  }
}

export function invalidUpload(message: string, status = 422): Response {
  return Response.json({ error: { code: "resume_multipart_invalid", message } }, { status });
}
