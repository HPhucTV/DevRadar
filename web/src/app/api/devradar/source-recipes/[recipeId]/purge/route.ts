import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CODE_PATTERN = /^RCP-[0-9A-F]{8}$/;

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_recipe_request_invalid", message: "Source recipe request is invalid." } },
    { status: 422 },
  );
}

export async function POST(request: Request, context: Context): Promise<Response> {
  const recipeId = (await context.params).recipeId;
  if (!UUID_PATTERN.test(recipeId)) return invalidRequest();
  let value: unknown;
  try { value = await request.json(); } catch { return invalidRequest(); }
  if (
    typeof value !== "object" || value === null || Array.isArray(value) ||
    Object.keys(value).join("|") !== "confirmationCode"
  ) return invalidRequest();
  const confirmationCode = (value as { confirmationCode?: unknown }).confirmationCode;
  if (typeof confirmationCode !== "string" || !CODE_PATTERN.test(confirmationCode)) {
    return invalidRequest();
  }
  return proxyBackend(request, `/source-recipes/${recipeId}/purge`, {
    method: "POST",
    body: JSON.stringify({ confirmationCode }),
  });
}
