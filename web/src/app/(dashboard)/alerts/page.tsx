import { AlertRulesPanel } from "@/components/alert-rules-panel";

export default function AlertsPage() {
  return <><section className="page-intro"><p className="eyebrow">Evidence-first notifications</p><h1>Alerts with a paper trail.</h1><p>Keep a small, explainable watchlist for the jobs that matter. This local/protected slice uses one Discord connector and makes replay behavior visible.</p></section><AlertRulesPanel /></>;
}
