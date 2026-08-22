import routes from "@/contracts/routes.json";

export function RoutePlaceholder({ routeId, context }: { routeId: string; context?: string }) {
  const route = routes.find((candidate) => candidate.id === routeId);
  if (!route) throw new Error("Unknown route contract.");
  return <section className="route-panel"><p className="status-line">{route.availability.replaceAll("_", " ")}</p><h1>{route.label}</h1><p className="route-description">{route.description}</p>{context ? <p className="route-context">{context}</p> : null}<h2>Data contract</h2>{route.apiResources.length ? <ul>{route.apiResources.map((resource) => <li key={resource}><code>{resource}</code></li>)}</ul> : <p>Backend contract is intentionally not available yet.</p>}<p className="handoff">Data rendering starts in the phase named by this route&apos;s availability.</p></section>;
}
