import { proxyBackend } from "@/lib/backend-proxy";

type Context = { params: Promise<{ profileId: string }> };

export async function GET(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/resume-profiles/${encodeURIComponent(profileId)}`);
}

export async function DELETE(request: Request, context: Context): Promise<Response> {
  const { profileId } = await context.params;
  return proxyBackend(request, `/resume-profiles/${encodeURIComponent(profileId)}`, { method: "DELETE" });
}
