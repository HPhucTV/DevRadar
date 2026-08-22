const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function backendUrl(path: string): string {
  const base = process.env.DEVRADAR_API_BASE_URL?.trim() || DEFAULT_API_BASE_URL;
  return new URL(`/api/v1${path}`, base).toString();
}

function ownerHeaders(request: Request): Headers {
  const headers = new Headers({ accept: "application/json" });
  const owner = request.headers.get("x-devradar-owner");
  if (owner) headers.set("x-devradar-owner", owner);
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
      headers: new Headers({ ...Object.fromEntries(ownerHeaders(request)), ...(init.headers ?? {}) }),
      cache: "no-store",
    });
    const headers = new Headers();
    const contentType = response.headers.get("content-type");
    if (contentType) headers.set("content-type", contentType);
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
