import { randomUUID } from "node:crypto";
import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_crawl_request_invalid", message: "Crawl request is invalid." } },
    { status: 422 },
  );
}

function paginationQuery(request: Request): string {
  const input = new URL(request.url).searchParams;
  const output = new URLSearchParams();
  for (const key of ["page", "pageSize"]) {
    const value = input.get(key);
    if (value && /^\d{1,3}$/.test(value)) output.set(key, value);
  }
  return output.size ? `?${output}` : "";
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const { recipeId } = await context.params;
  if (!UUID_PATTERN.test(recipeId)) return invalidRequest();
  return proxyBackend(request, `/source-recipes/${recipeId}/crawl-runs${paginationQuery(request)}`);
}

export async function POST(request: Request, context: Context): Promise<Response> {
  const { recipeId } = await context.params;
  if (!UUID_PATTERN.test(recipeId)) return invalidRequest();
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalidRequest();
  }
  if (typeof body !== "object" || body === null || Array.isArray(body) || Object.keys(body).length) {
    return invalidRequest();
  }
  const idempotencyKey = request.headers.get("idempotency-key")?.trim() || randomUUID();
  if (!IDEMPOTENCY_PATTERN.test(idempotencyKey)) return invalidRequest();
  return proxyBackend(request, `/source-recipes/${recipeId}/crawl-runs`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: "{}",
  });
}
