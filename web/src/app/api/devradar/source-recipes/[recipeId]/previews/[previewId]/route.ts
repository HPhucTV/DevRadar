import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string; previewId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_preview_request_invalid", message: "Preview identifier is invalid." } },
    { status: 422 },
  );
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const { recipeId, previewId } = await context.params;
  if (!UUID_PATTERN.test(recipeId) || !UUID_PATTERN.test(previewId)) return invalidRequest();
  return proxyBackend(request, `/source-recipes/${recipeId}/previews/${previewId}`);
}
