import { proxyBackend } from "@/lib/backend-proxy";

export async function POST(request: Request): Promise<Response> {
  return proxyBackend(request, "/auth/logout", { method: "POST" });
}
