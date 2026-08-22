import { proxyBackend } from "@/lib/backend-proxy";

export async function POST(request: Request): Promise<Response> {
  let body: string;
  try {
    body = await request.text();
    JSON.parse(body);
  } catch {
    return Response.json({ error: { code: "auth_invalid_request", message: "Login request is invalid." } }, { status: 422 });
  }
  return proxyBackend(request, "/auth/login", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body,
  });
}
