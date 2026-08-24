import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string; previewId: string }> };
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const MAPPING_FIELDS = new Set([
  "cardElementId",
  "titleElementId",
  "companyElementId",
  "locationElementId",
  "jobUrlElementId",
  "paginationElementId",
]);

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "source_mapping_request_invalid", message: "Mapping request is invalid." } },
    { status: 422 },
  );
}

export async function POST(request: Request, context: Context): Promise<Response> {
  const { recipeId, previewId } = await context.params;
  if (!UUID_PATTERN.test(recipeId) || !UUID_PATTERN.test(previewId)) return invalidRequest();
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalidRequest();
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalidRequest();
  if (Object.keys(body).some((key) => !MAPPING_FIELDS.has(key))) return invalidRequest();
  return proxyBackend(request, `/source-recipes/${recipeId}/previews/${previewId}/mapping`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}
