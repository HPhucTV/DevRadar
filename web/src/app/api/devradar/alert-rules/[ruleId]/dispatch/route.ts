import { proxyBackend } from "@/lib/backend-proxy";
type Context = { params: Promise<{ ruleId: string }> };
export async function POST(request: Request, context: Context): Promise<Response> { const { ruleId } = await context.params; return proxyBackend(request, `/alert-rules/${encodeURIComponent(ruleId)}/dispatch?maxItems=5`, { method: "POST" }); }
