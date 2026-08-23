import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ profileId: string }> };

export async function POST(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/custom-sources/${encodeURIComponent(profileId)}/preview`, { method: "POST" });
}
