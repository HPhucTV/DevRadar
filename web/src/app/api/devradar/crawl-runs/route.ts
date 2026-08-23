import { randomUUID } from "node:crypto";
import { proxyBackend } from "@/lib/backend-proxy";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

function invalidRequest(): Response {
  return Response.json(
    { error: { code: "ingestion_request_invalid", message: "Only an approved sourceId is accepted." } },
    { status: 422 },
  );
}

export async function GET(request: Request): Promise<Response> {
  return proxyBackend(request, `/crawl-runs${new URL(request.url).search}`);
}

export async function POST(request: Request): Promise<Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalidRequest();
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalidRequest();
  const fields = Object.keys(body);
  const sourceId = (body as { sourceId?: unknown }).sourceId;
  if (fields.length !== 1 || fields[0] !== "sourceId" || typeof sourceId !== "string" || !UUID_PATTERN.test(sourceId)) {
    return invalidRequest();
  }
  const idempotencyKey = request.headers.get("idempotency-key")?.trim() || randomUUID();
  if (!IDEMPOTENCY_PATTERN.test(idempotencyKey)) return invalidRequest();
  return proxyBackend(request, "/crawl-runs", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey },
    body: JSON.stringify({ sourceId }),
  });
}
