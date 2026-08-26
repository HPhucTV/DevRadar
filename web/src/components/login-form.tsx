"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ApiErrorState } from "@/components/api-state";
import { useI18n } from "@/i18n/locale-provider";
import { login } from "@/lib/auth";
import type { ApiFailure } from "@/lib/api";

export function LoginForm() {
  const { dictionary } = useI18n();
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

  return <section className="auth-surface glass-surface auth-panel"><p className="route-label">{dictionary.auth.sessionEyebrow}</p><h1>{dictionary.auth.title}</h1><p className="field-help">{dictionary.auth.body}</p><form className="cv-form" onSubmit={submit}><label>{dictionary.auth.username}<input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required minLength={3} maxLength={64} /></label><label>{dictionary.auth.password}<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required maxLength={1024} /></label><button type="submit" disabled={busy}>{busy ? dictionary.auth.signingIn : dictionary.auth.signIn}</button></form>{error ? <ApiErrorState error={error} /> : null}</section>;
}
