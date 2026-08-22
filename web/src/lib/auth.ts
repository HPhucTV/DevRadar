import type { ApiFailure, ApiResult } from "@/lib/api";
import { sessionFetch } from "@/lib/session-request";

export type AuthUser = { username: string; role: "owner" | "operator" };
type AuthUserResponse = { data: AuthUser };
type LoginResponse = { data: { user: AuthUser; csrfToken: string } };

function isRecord(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null; }
function isUser(value: unknown): value is AuthUser { return isRecord(value) && typeof value.username === "string" && (value.role === "owner" || value.role === "operator"); }
function failure(status: number, body: unknown): ApiFailure { const error = isRecord(body) && isRecord(body.error) ? body.error : {}; return { kind: "error", status, code: typeof error.code === "string" ? error.code : "http_error", message: typeof error.message === "string" ? error.message : "Authentication request failed." }; }

export async function login(username: string, password: string): Promise<ApiResult<LoginResponse>> {
  try {
    const response = await fetch("/api/devradar/auth/login", { method: "POST", credentials: "include", headers: { accept: "application/json", "content-type": "application/json" }, body: JSON.stringify({ username, password }) });
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body);
    if (!isRecord(body) || !isRecord(body.data) || !isUser(body.data.user) || typeof body.data.csrfToken !== "string") return failure(response.status, { error: { code: "invalid_contract", message: "Login response did not match the documented contract." } });
    return { kind: "success", value: body as LoginResponse };
  } catch { return failure(503, { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } }); }
}

export async function currentUser(): Promise<ApiResult<AuthUserResponse>> {
  try {
    const response = await sessionFetch("/api/devradar/auth/me");
    const body: unknown = await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body);
    if (!isRecord(body) || !isUser(body.data)) return failure(response.status, { error: { code: "invalid_contract", message: "Session response did not match the documented contract." } });
    return { kind: "success", value: body as AuthUserResponse };
  } catch { return failure(503, { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } }); }
}

export async function logout(): Promise<ApiResult<null>> {
  try {
    const response = await sessionFetch("/api/devradar/auth/logout", { method: "POST" });
    const body: unknown = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) return failure(response.status, body);
    return { kind: "success", value: null };
  } catch { return failure(503, { error: { code: "backend_unavailable", message: "DevRadar API is not reachable." } }); }
}
