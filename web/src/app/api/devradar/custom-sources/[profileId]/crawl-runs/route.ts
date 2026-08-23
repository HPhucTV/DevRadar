import { randomUUID } from "node:crypto";
import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ profileId: string }> };
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

function paginationQuery(request: Request): string {
  const input = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["page", "pageSize"]) {
    const value = input.get(key);
    if (value && /^\d{1,3}$/.test(value)) query.set(key, value);
  }
  return query.toString() ? `?${query}` : "";
}

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "custom_crawl_request_invalid", message: "A bounded idempotency key is required." } },
    { status: 422 },
  );
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/custom-sources/${encodeURIComponent(profileId)}/crawl-runs${paginationQuery(request)}`);
}

export async function POST(request: Request, context: Context): Promise<Response> {
  const requestedKey = request.headers.get("idempotency-key")?.trim() || randomUUID();
  if (!IDEMPOTENCY_PATTERN.test(requestedKey)) return invalidRequest();
  const { profileId } = await context.params;
  return proxyBackend(request, `/custom-sources/${encodeURIComponent(profileId)}/crawl-runs`, {
    method: "POST",
    headers: { "Idempotency-Key": requestedKey },
  });
}
