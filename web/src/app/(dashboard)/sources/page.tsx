import { CustomSourcePanel } from "@/components/custom-source-panel";
import { getI18n } from "@/i18n/server";

export default async function CustomSourcesPage() {
  const { dictionary } = await getI18n();
  return (
    <>
      <section className="page-intro">
        <p className="eyebrow">{dictionary.customSources.pageEyebrow}</p>
        <h1>{dictionary.customSources.pageTitle}</h1>
        <p>{dictionary.customSources.pageBody}</p>
      </section>
      <CustomSourcePanel />
    </>
  );
}
