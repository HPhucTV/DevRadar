import Link from "next/link";
import type { ReactNode } from "react";
import { AuthControls } from "@/components/auth-controls";
import { LanguageSwitcher } from "@/components/language-switcher";
import { PrimaryNavigation } from "@/components/primary-navigation";
import { getI18n } from "@/i18n/server";
import { localNoLoginEnabled } from "@/lib/deployment-mode";

export async function AppShell({ children }: { children: ReactNode }) {
  const noLogin = localNoLoginEnabled();
  const { dictionary } = await getI18n();
  return (
    <div className="app-canvas">
      <a className="skip-link" href="#main-content">{dictionary.shell.skipToContent}</a>
      <div aria-hidden="true" className="ambient ambient-one" />
      <div aria-hidden="true" className="ambient ambient-two" />
      <div className="app-shell">
        <aside className="sidebar-shell glass-surface">
          <Link className="brand-lockup" href="/">
            <span aria-hidden="true" className="brand-mark">D</span>
            <span className="brand-copy">
              <span className="brand">DevRadar</span>
              <span className="brand-subtitle">{dictionary.shell.subtitle}</span>
            </span>
          </Link>
          <PrimaryNavigation />
        </aside>
        <div className="workspace-shell">
          <header className="workspace-header glass-surface">
            <span className="phase-badge">
              {noLogin ? dictionary.shell.phaseLocal : dictionary.shell.phaseSession}
            </span>
            <div className="header-actions">
              <LanguageSwitcher />
              <AuthControls localNoLoginEnabled={noLogin} />
            </div>
          </header>
          <main id="main-content">{children}</main>
        </div>
      </div>
    </div>
  );
}
