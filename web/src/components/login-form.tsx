"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiErrorState } from "@/components/api-state";
import { login } from "@/lib/auth";
import type { ApiFailure } from "@/lib/api";

export function LoginForm() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<ApiFailure | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const result = await login(username, password);
    if (result.kind === "error") {
      setError(result);
      setBusy(false);
      return;
    }
    setPassword("");
    router.push("/");
    router.refresh();
  }

  return <section className="content-section auth-panel"><p className="eyebrow">V6 authenticated session</p><h1>Sign in to DevRadar</h1><p className="field-help">The server stores only a password hash. Session and CSRF credentials are never placed in localStorage or the URL.</p><form className="cv-form" onSubmit={submit}><label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} /></label><label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={1024} /></label><button type="submit" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</button></form>{error ? <ApiErrorState error={error} /> : null}</section>;
}
