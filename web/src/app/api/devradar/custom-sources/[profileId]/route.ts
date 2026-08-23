import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ profileId: string }> };
// Next.js Route Handlers expose dynamic params as a promise in the current App Router.
// Source: https://nextjs.org/docs/app/api-reference/file-conventions/route
const PROFILE_FIELDS = new Set([
  "name", "base_url", "allowed_hosts", "allowed_path_prefixes", "parser_mode", "field_mapping",
  "schedule_kind", "interval_minutes", "daily_at", "timezone", "item_budget",
  "byte_budget", "requests_per_minute", "permission_acknowledged", "status",
]);

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "custom_source_request_invalid", message: "Only validated custom source fields are accepted." } },
    { status: 422 },
  );
}

async function profileId(context: Context): Promise<string> {
  return encodeURIComponent((await context.params).profileId);
}

async function safeBody(request: Request): Promise<string | Response> {
  let body: unknown;
  try { body = await request.json(); } catch { return invalidRequest(); }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalidRequest();
  if (Object.keys(body).some((key) => !PROFILE_FIELDS.has(key))) return invalidRequest();
  return JSON.stringify(body);
}

export async function GET(request: Request, context: Context): Promise<Response> {
  return proxyBackend(request, `/custom-sources/${await profileId(context)}`);
}

export async function PATCH(request: Request, context: Context): Promise<Response> {
  const body = await safeBody(request);
  if (body instanceof Response) return body;
  return proxyBackend(request, `/custom-sources/${await profileId(context)}`, { method: "PATCH", body });
}

export async function DELETE(request: Request, context: Context): Promise<Response> {
  return proxyBackend(request, `/custom-sources/${await profileId(context)}`, { method: "DELETE" });
}
