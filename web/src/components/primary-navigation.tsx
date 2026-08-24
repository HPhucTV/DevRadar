"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef, useState, type KeyboardEvent } from "react";
import routes from "@/contracts/routes.json";
import { useI18n } from "@/i18n/locale-provider";

export function PrimaryNavigation() {
  const pathname = usePathname();
  const { dictionary } = useI18n();
  const [open, setOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const routeLabels: Record<string, string> = {
    overview: dictionary.routes.overview,
    jobs: dictionary.routes.jobs,
    analytics: dictionary.routes.analytics,
    "crawler-health": dictionary.routes.crawlerHealth,
    "cv-match": dictionary.routes.cvMatch,
    alerts: dictionary.routes.alerts,
    "custom-sources": dictionary.routes.customSources,
  };

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      toggleRef.current?.focus();
    }
  }

  return (
    <nav
      aria-label={dictionary.shell.primaryNavigation}
      className="primary-nav"
      onKeyDown={handleKeyDown}
    >
      <button
        aria-controls="primary-navigation-links"
        aria-expanded={open}
        className="nav-toggle"
        onClick={() => setOpen((current) => !current)}
        ref={toggleRef}
        type="button"
      >
        <span aria-hidden="true" className="nav-toggle-icon">
          <span />
          <span />
          <span />
        </span>
        <span>{dictionary.shell.navigationMenu}</span>
      </button>
      <div
        className={`nav-links${open ? " is-open" : ""}`}
        id="primary-navigation-links"
      >
        {routes.filter((route) => route.showInNav).map((route) => {
          const isActive = route.path === "/"
            ? pathname === "/"
            : pathname === route.path || pathname.startsWith(`${route.path}/`);
          return (
            <Link
              aria-current={isActive ? "page" : undefined}
              href={route.path}
              key={route.id}
              onClick={() => setOpen(false)}
            >
              {routeLabels[route.id] ?? route.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
