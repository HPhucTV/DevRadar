import { randomUUID } from "node:crypto";
import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ recipeId: string }> };

export const MAX_SOURCE_DOCUMENT_BYTES = 2 * 1024 * 1024;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const IDEMPOTENCY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$/;

function invalidDocumentImport(message: string, status = 422): Response {
  return Response.json(
    { error: { code: "source_document_import_invalid", message } },
    { status },
  );
}

export async function POST(request: Request, context: Context): Promise<Response> {
  const { recipeId } = await context.params;
  if (!UUID_PATTERN.test(recipeId)) return invalidDocumentImport("Recipe ID is invalid.");

  let incoming: FormData;
  try {
    incoming = await request.formData();
  } catch {
    return invalidDocumentImport("Upload must contain exactly one file part.");
  }

  const parts = Array.from(incoming.entries());
  if (parts.length !== 1) {
    return invalidDocumentImport("Upload must contain exactly one file part.");
  }
  const [fieldName, file] = parts[0];
  if (fieldName !== "file" || !(file instanceof File)) {
    return invalidDocumentImport("Upload must contain exactly one file part.");
  }
  if (file.size > MAX_SOURCE_DOCUMENT_BYTES) {
    return invalidDocumentImport("Source document exceeds the 2 MiB upload limit.", 413);
  }

  const idempotencyKey = request.headers.get("idempotency-key")?.trim() || randomUUID();
  if (!IDEMPOTENCY_PATTERN.test(idempotencyKey)) {
    return invalidDocumentImport("Idempotency key is invalid.");
  }

  const form = new FormData();
  form.append("file", file, file.name || "jobs-document");
  return proxyBackend(request, `/source-recipes/${recipeId}/document-imports`, {
    method: "POST",
    headers: { "Idempotency-Key": idempotencyKey },
    body: form,
  });
}
