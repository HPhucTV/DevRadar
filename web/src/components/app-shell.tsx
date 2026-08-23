import Link from "next/link";
import type { ReactNode } from "react";
import routes from "@/contracts/routes.json";
import { AuthControls } from "@/components/auth-controls";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand-lockup" href="/">
          <span aria-hidden="true" className="brand-mark">D</span>
          <span className="brand-copy"><span className="brand">DevRadar</span><span className="eyebrow">Vietnam IT market evidence</span></span>
        </Link>
        <div className="header-actions"><span className="phase-badge">V6 session</span><AuthControls /></div>
      </header>
      <nav aria-label="Primary navigation" className="primary-nav nav-group">
        {routes.filter((route) => route.showInNav).map((route) => <Link href={route.path} key={route.id}>{route.label}</Link>)}
      </nav>
      <main id="main-content">{children}</main>
      <footer className="site-footer"><Link href="/privacy">Privacy & source policy</Link></footer>
    </div>
  );
}
