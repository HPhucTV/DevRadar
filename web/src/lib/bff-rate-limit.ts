import { createHash } from "node:crypto";

type Bucket = { count: number; resetAt: number };

const buckets = new Map<string, Bucket>();
const MAX_KEYS = 10_000;
const GENERAL_LIMIT = 120;
const GENERAL_WINDOW_MS = 60_000;
const AUTH_LIMIT = 10;
const AUTH_WINDOW_MS = 15 * 60_000;

function policy(path: string): { limit: number; windowMs: number } {
  return path === "/auth/login"
    ? { limit: AUTH_LIMIT, windowMs: AUTH_WINDOW_MS }
    : { limit: GENERAL_LIMIT, windowMs: GENERAL_WINDOW_MS };
}

export function bffRateLimit(request: Request, path: string): Response | null {
  const { limit, windowMs } = policy(path);
  const cookie = request.headers.get("cookie") ?? "anonymous";
  const fingerprint = createHash("sha256").update(cookie).digest("hex").slice(0, 16);
  const key = `${path}:${fingerprint}`;
  const now = Date.now();
  const current = buckets.get(key);
  if (!current || now >= current.resetAt) {
    while (buckets.size >= MAX_KEYS) buckets.delete(buckets.keys().next().value ?? key);
    buckets.set(key, { count: 1, resetAt: now + windowMs });
    return null;
  }
  if (current.count >= limit) {
    const retryAfter = Math.max(1, Math.ceil((current.resetAt - now) / 1000));
    return Response.json(
      { error: { code: "rate_limited", message: "Request rate limit exceeded." } },
      {
        status: 429,
        headers: {
          "Retry-After": String(retryAfter),
          "X-RateLimit-Limit": String(limit),
          "X-RateLimit-Remaining": "0",
        },
      },
    );
  }
  current.count += 1;
  return null;
}
