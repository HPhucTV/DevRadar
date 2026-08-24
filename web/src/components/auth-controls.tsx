"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useI18n } from "@/i18n/locale-provider";
import { currentUser, logout, type AuthUser } from "@/lib/auth";

export function AuthControls({ localNoLoginEnabled }: { localNoLoginEnabled: boolean }) {
  if (localNoLoginEnabled) return null;
  return <SessionAuthControls />;
}

function SessionAuthControls() {
  const { dictionary } = useI18n();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void currentUser().then((result) => {
      if (result.kind === "success") setUser(result.value.data);
    });
  }, []);

  async function signOut() {
    setBusy(true);
    const result = await logout();
    if (result.kind === "success") setUser(null);
    setBusy(false);
  }

  return user ? <span className="auth-controls"><span>{user.username} · {dictionary.status[user.role]}</span><button type="button" onClick={() => void signOut()} disabled={busy}>{busy ? dictionary.auth.signingOut : dictionary.auth.signOut}</button></span> : <Link href="/login">{dictionary.auth.signIn}</Link>;
}
