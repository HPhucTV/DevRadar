export function csrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const pair = document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("devradar_csrf="));
  return pair ? decodeURIComponent(pair.slice("devradar_csrf=".length)) : null;
}

export function sessionFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (!headers.has("accept")) headers.set("accept", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const token = csrfToken();
    if (token) headers.set("X-DevRadar-CSRF", token);
  }
  return fetch(input, { ...init, credentials: "include", headers, cache: "no-store" });
}
