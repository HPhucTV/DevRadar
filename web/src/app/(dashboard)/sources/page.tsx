import { SourceRecipePanel } from "@/components/source-recipe-panel";
import { getI18n } from "@/i18n/server";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const VIEWS = new Set(["active", "collector", "retired", "all"]);
function first(value: string | string[] | undefined): string | undefined { return Array.isArray(value) ? value[0] : value; }

export default async function SourcesPage({ searchParams }: { searchParams: SearchParams }) {
  const { dictionary } = await getI18n();
  const query = await searchParams;
  const recipeId = first(query.recipeId);
  const view = first(query.view);
  return (
    <>
      <section className="route-header route-header--compact">
        <p className="route-label">{dictionary.sourceRecipes.pageEyebrow}</p>
        <h1>{dictionary.sourceRecipes.pageTitle}</h1>
        <p>{dictionary.sourceRecipes.pageBody}</p>
      </section>
      <SourceRecipePanel
        initialRecipeId={recipeId && UUID_PATTERN.test(recipeId) ? recipeId : null}
        initialView={view && VIEWS.has(view) ? view as "active" | "collector" | "retired" | "all" : "active"}
      />
    </>
  );
}
