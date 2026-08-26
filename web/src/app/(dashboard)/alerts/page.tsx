import { AlertRulesPanel } from "@/components/alert-rules-panel";
import { getI18n } from "@/i18n/server";

export default async function AlertsPage() {
  const { dictionary } = await getI18n();
  return <><section className="route-header route-header--compact"><p className="route-label">{dictionary.alerts.pageEyebrow}</p><h1>{dictionary.alerts.pageTitle}</h1><p>{dictionary.alerts.pageBody}</p></section><AlertRulesPanel /></>;
}
