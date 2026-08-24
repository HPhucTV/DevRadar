import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_preview_request_invalid", message: "Preview request is invalid." } },
    { status: 422 },
  );
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
  return proxyBackend(request, `/source-recipes/${recipeId}/previews`, {
    method: "POST",
    body: "{}",
  });
}
