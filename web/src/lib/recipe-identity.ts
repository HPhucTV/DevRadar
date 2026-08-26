type RecipeIdentityInput = {
  id: string;
  name: string;
  listingUrl: string;
  seniorityFilter: string[];
};

export function isCollectorRecipe(recipe: RecipeIdentityInput): boolean {
  return /^Collector\s*·\s*/i.test(recipe.name);
}

export function recipeDisplayName(
  recipe: RecipeIdentityInput,
  labels: Record<string, string>,
): string {
  if (!isCollectorRecipe(recipe)) return recipe.name;
  let hostname: string;
  try { hostname = new URL(recipe.listingUrl).hostname.replace(/^www\./i, ""); }
  catch { hostname = recipe.name.replace(/^Collector\s*·\s*/i, "").trim(); }
  const values = recipe.seniorityFilter.length ? recipe.seniorityFilter : ["all"];
  const seniority = values.map((value) => labels[value] ?? value).join(", ");
  return `${hostname} · ${seniority}`;
}

export function sortRecipes<T extends { id: string; name: string }>(
  recipes: T[],
  selectedId: string | null,
): T[] {
  return [...recipes].sort((left, right) => {
    if (left.id === selectedId) return -1;
    if (right.id === selectedId) return 1;
    return left.name.localeCompare(right.name);
  });
}
