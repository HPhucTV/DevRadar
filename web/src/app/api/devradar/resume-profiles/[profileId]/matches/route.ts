import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ profileId: string }> };

export async function POST(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/resume-profiles/${encodeURIComponent(profileId)}/matches`, { method: "POST" });
}

export async function GET(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/resume-profiles/${encodeURIComponent(profileId)}/matches?page=1&pageSize=20`);
}
