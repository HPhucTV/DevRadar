import { SourceRecipePanel } from "@/components/source-recipe-panel";
import { getI18n } from "@/i18n/server";

export default async function SourcesPage() {
  const { dictionary } = await getI18n();
  return (
    <>
      <section className="route-header route-header--compact">
        <p className="route-label">{dictionary.sourceRecipes.pageEyebrow}</p>
        <h1>{dictionary.sourceRecipes.pageTitle}</h1>
        <p>{dictionary.sourceRecipes.pageBody}</p>
      </section>
      <SourceRecipePanel />
    </>
  );
}
