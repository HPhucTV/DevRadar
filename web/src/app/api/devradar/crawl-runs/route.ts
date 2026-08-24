import { proxyBackend } from "@/lib/backend-proxy";

export async function GET(request: Request): Promise<Response> {
  return proxyBackend(request, `/crawl-runs${new URL(request.url).search}`);
}
