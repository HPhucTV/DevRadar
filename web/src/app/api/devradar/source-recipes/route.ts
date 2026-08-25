import { proxyBackend } from "@/lib/backend-proxy";

const RECIPE_FIELDS = new Set([
  "name",
  "listingUrl",
  "seniorityFilter",
  "acknowledgedNoticeVersion",
  "scheduleKind",
  "scheduleLocalTime",
  "scheduleWeekday",
  "timezone",
  "itemBudget",
  "pageBudget",
  "requestBudget",
  "byteBudget",
  "timeBudgetSeconds",
  "requestsPerMinute",
]);

function invalidRequest(): Response {
  return Response.json(
    {
      error: {
        code: "source_recipe_request_invalid",
        message: "Only validated source recipe fields are accepted.",
      },
    },
    { status: 422 },
  );
}

function paginationQuery(request: Request): string {
  const input = new URL(request.url).searchParams;
  const output = new URLSearchParams();
  for (const key of ["page", "pageSize"]) {
    const value = input.get(key);
    if (value && /^\d{1,3}$/.test(value)) output.set(key, value);
  }
  return output.size ? `?${output}` : "";
}

async function safeBody(request: Request): Promise<string | Response> {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return invalidRequest();
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) return invalidRequest();
  if (Object.keys(body).some((key) => !RECIPE_FIELDS.has(key))) return invalidRequest();
  return JSON.stringify(body);
}

export async function GET(request: Request): Promise<Response> {
  return proxyBackend(request, `/source-recipes${paginationQuery(request)}`);
}

export async function POST(request: Request): Promise<Response> {
  const body = await safeBody(request);
  if (body instanceof Response) return body;
  return proxyBackend(request, "/source-recipes", { method: "POST", body });
}
