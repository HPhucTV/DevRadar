import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PATCH_FIELDS = new Set([
  "name",
  "seniorityFilter",
  "allowedHosts",
  "allowedPathPrefixes",
  "scheduleKind",
  "scheduleLocalTime",
  "scheduleWeekday",
  "timezone",
  "status",
]);

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_recipe_request_invalid", message: "Source recipe request is invalid." } },
    { status: 422 },
  );
}

async function id(context: Context): Promise<string | null> {
  const value = (await context.params).recipeId;
  return UUID_PATTERN.test(value) ? value : null;
}

async function body(request: Request): Promise<string | Response> {
  let value: unknown;
  try {
    value = await request.json();
  } catch {
    return invalidRequest();
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) return invalidRequest();
  if (Object.keys(value).some((key) => !PATCH_FIELDS.has(key))) return invalidRequest();
  return JSON.stringify(value);
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const recipeId = await id(context);
  return recipeId ? proxyBackend(request, `/source-recipes/${recipeId}`) : invalidRequest();
}

export async function PATCH(request: Request, context: Context): Promise<Response> {
  const recipeId = await id(context);
  if (!recipeId) return invalidRequest();
  const payload = await body(request);
  if (payload instanceof Response) return payload;
  return proxyBackend(request, `/source-recipes/${recipeId}`, { method: "PATCH", body: payload });
}

export async function DELETE(request: Request, context: Context): Promise<Response> {
  const recipeId = await id(context);
  return recipeId
    ? proxyBackend(request, `/source-recipes/${recipeId}`, { method: "DELETE" })
    : invalidRequest();
}
