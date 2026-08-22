"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { currentUser, logout, type AuthUser } from "@/lib/auth";

export function AuthControls() {
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

  return user ? <span className="auth-controls"><span>{user.username} · {user.role}</span><button type="button" onClick={() => void signOut()} disabled={busy}>{busy ? "Signing out..." : "Sign out"}</button></span> : <Link href="/login">Sign in</Link>;
}
