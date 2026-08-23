import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ runId: string }> };

export async function GET(request: Request, context: Context): Promise<Response> {
  const { runId } = await context.params;
  return proxyBackend(request, `/crawl-runs/${encodeURIComponent(runId)}`);
}
