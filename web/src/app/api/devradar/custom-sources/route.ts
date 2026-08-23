import { proxyBackend } from "@/lib/backend-proxy";

const PROFILE_FIELDS = new Set([
  "name", "base_url", "allowed_hosts", "allowed_path_prefixes", "parser_mode", "field_mapping",
  "schedule_kind", "interval_minutes", "daily_at", "timezone", "item_budget",
  "byte_budget", "requests_per_minute", "permission_acknowledged",
]);

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "custom_source_request_invalid", message: "Only validated custom source fields are accepted." } },
    { status: 422 },
  );
}

function paginationQuery(request: Request): string {
  const input = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["page", "pageSize"]) {
    const value = input.get(key);
    if (value && /^\d{1,3}$/.test(value)) query.set(key, value);
  }
  return query.toString() ? `?${query}` : "";
}

async function safeBody(request: Request): Promise<string | Response> {
  let body: unknown;
  try { body = await request.json(); } catch { return invalidRequest(); }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalidRequest();
  const keys = Object.keys(body);
  if (keys.some((key) => !PROFILE_FIELDS.has(key))) return invalidRequest();
  return JSON.stringify(body);
}

export async function GET(request: Request): Promise<Response> {
  return proxyBackend(request, `/custom-sources${paginationQuery(request)}`);
}

export async function POST(request: Request): Promise<Response> {
  const body = await safeBody(request);
  if (body instanceof Response) return body;
  return proxyBackend(request, "/custom-sources", { method: "POST", body });
}
