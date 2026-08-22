import { MAX_RESUME_BYTES } from "@/lib/cv-match";
import { invalidUpload, proxyBackend } from "@/lib/backend-proxy";

export async function POST(request: Request): Promise<Response> {
  let incoming: FormData;
  try {
    incoming = await request.formData();
  } catch {
    return invalidUpload("Upload must contain exactly one file part.");
  }
  const file = incoming.get("file");
  if (!(file instanceof File)) return invalidUpload("Upload must contain exactly one file part.");
  if (file.size > MAX_RESUME_BYTES) return invalidUpload("Resume exceeds the upload limit.", 413);
  const form = new FormData();
  form.append("file", file, file.name || "resume");
  return proxyBackend(request, "/resume-profiles", { method: "POST", body: form });
}
