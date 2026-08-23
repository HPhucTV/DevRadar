import Link from "next/link";
import type { ReactNode } from "react";
import routes from "@/contracts/routes.json";
import { AuthControls } from "@/components/auth-controls";

export function AppShell({ children }: { children: ReactNode }) {
  return <div className="app-shell"><header className="site-header"><div><Link className="brand" href="/">DevRadar</Link><p className="eyebrow">Vietnam IT market evidence</p></div><span className="phase-badge">V6 session</span><AuthControls /></header><nav aria-label="Primary navigation" className="primary-nav">{routes.filter((route) => route.showInNav).map((route) => <Link href={route.path} key={route.id}>{route.label}</Link>)}</nav><main id="main-content">{children}</main><footer className="site-footer"><Link href="/privacy">Privacy & source policy</Link></footer></div>;
}
