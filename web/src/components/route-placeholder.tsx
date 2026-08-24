"use client";
import routes from "@/contracts/routes.json";
import { useI18n } from "@/i18n/locale-provider";

export function RoutePlaceholder({ routeId, context }: { routeId: string; context?: string }) {
  const { dictionary } = useI18n();
  const route = routes.find((candidate) => candidate.id === routeId);
  if (!route) throw new Error(dictionary.routePlaceholder.unknown);
  const labels: Record<string, string> = { overview: dictionary.routes.overview, jobs: dictionary.routes.jobs, analytics: dictionary.routes.analytics, "crawler-health": dictionary.routes.crawlerHealth, "cv-match": dictionary.routes.cvMatch, alerts: dictionary.routes.alerts };
  const availability = route.availability === "implemented" ? dictionary.routePlaceholder.implemented : dictionary.routePlaceholder.scaffolded;
  return <section className="route-panel"><p className="status-line">{availability}</p><h1>{labels[route.id] ?? route.label}</h1><p className="route-description">{dictionary.routePlaceholder.description}</p>{context ? <p className="route-context">{context}</p> : null}<h2>{dictionary.routePlaceholder.dataContract}</h2>{route.apiResources.length ? <ul>{route.apiResources.map((resource) => <li key={resource}><code>{resource}</code></li>)}</ul> : <p>{dictionary.routePlaceholder.noContract}</p>}<p className="handoff">{dictionary.routePlaceholder.handoff}</p></section>;
}
