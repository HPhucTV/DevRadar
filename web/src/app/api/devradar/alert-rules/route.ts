import { proxyBackend } from "@/lib/backend-proxy";

export async function GET(request: Request): Promise<Response> { return proxyBackend(request, `/alert-rules${new URL(request.url).search}`); }
export async function POST(request: Request): Promise<Response> { let body: unknown; try { body = await request.json(); } catch { return Response.json({ error: { code: "alert_rule_invalid", message: "Alert rule body is invalid." } }, { status: 422 }); } if (typeof body !== "object" || body === null || Array.isArray(body)) return Response.json({ error: { code: "alert_rule_invalid", message: "Alert rule body is invalid." } }, { status: 422 }); return proxyBackend(request, "/alert-rules", { method: "POST", body: JSON.stringify(body) }); }
