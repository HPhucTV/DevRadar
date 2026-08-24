import Link from "next/link";
import type { ReactNode } from "react";
import routes from "@/contracts/routes.json";
import { AuthControls } from "@/components/auth-controls";
import { LanguageSwitcher } from "@/components/language-switcher";
import { getI18n } from "@/i18n/server";
import { localNoLoginEnabled } from "@/lib/deployment-mode";

export async function AppShell({ children }: { children: ReactNode }) {
  const noLogin = localNoLoginEnabled();
  const { dictionary } = await getI18n();
  const routeLabels: Record<string, string> = {
    overview: dictionary.routes.overview,
    jobs: dictionary.routes.jobs,
    analytics: dictionary.routes.analytics,
    "crawler-health": dictionary.routes.crawlerHealth,
    "cv-match": dictionary.routes.cvMatch,
    alerts: dictionary.routes.alerts,
    "custom-sources": dictionary.routes.customSources,
  };
  return (
    <div className="app-shell">
      <header className="site-header">
        <Link className="brand-lockup" href="/">
          <span aria-hidden="true" className="brand-mark">D</span>
          <span className="brand-copy"><span className="brand">DevRadar</span><span className="eyebrow">{dictionary.shell.subtitle}</span></span>
        </Link>
        <div className="header-actions"><span className="phase-badge">{noLogin ? dictionary.shell.phaseLocal : dictionary.shell.phaseSession}</span><LanguageSwitcher /><AuthControls localNoLoginEnabled={noLogin} /></div>
      </header>
      <nav aria-label={dictionary.shell.primaryNavigation} className="primary-nav nav-group">
        {routes.filter((route) => route.showInNav).map((route) => <Link href={route.path} key={route.id}>{routeLabels[route.id] ?? route.label}</Link>)}
      </nav>
      <main id="main-content">{children}</main>
      <footer className="site-footer"><Link href="/privacy">{dictionary.shell.privacy}</Link></footer>
    </div>
  );
}
