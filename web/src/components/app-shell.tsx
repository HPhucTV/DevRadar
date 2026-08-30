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
            <span aria-hidden="true" className="brand-mark">
              <svg width="22" height="22" viewBox="0 0 80 80" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="40" cy="40" r="34" stroke="#ffffff" stroke-width="2.5" stroke-dasharray="3 4" stroke-opacity="0.6"/>
                <circle cx="40" cy="40" r="22" stroke="#ffffff" stroke-width="2.5" stroke-opacity="0.85"/>
                <circle cx="40" cy="40" r="6" fill="#ffffff"/>
                <path d="M40 40 L66 22 A 32 32 0 0 0 40 8 Z" fill="#ffffff" opacity="0.3"/>
                <line x1="40" y1="40" x2="66" y2="22" stroke="#ffffff" stroke-width="2.5"/>
                <circle cx="56" cy="26" r="3.5" fill="#a7f3d0"/>
                <path d="M30 36L26 40L30 44" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M50 36L54 40L50 44" stroke="#ffffff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
            </span>
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
