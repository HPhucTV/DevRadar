import assert from "node:assert/strict";
import test from "node:test";

import {
  isCollectorRecipe,
  recipeDisplayName,
  sortRecipes,
} from "../src/lib/recipe-identity.ts";

const collector = {
  id: "f1fe63e0-61dc-40b7-93c2-72c670c28155",
  name: "Collector · www.topcv.vn",
  listingUrl: "https://www.topcv.vn/jobs",
  seniorityFilter: ["intern"],
};

test("collector recipe gets one bounded operator label", () => {
  assert.equal(isCollectorRecipe(collector), true);
  assert.equal(recipeDisplayName(collector, { intern: "Intern", all: "All" }), "topcv.vn · Intern");
});

test("custom name stays intact and selected recipe sorts first", () => {
  const custom = { ...collector, id: "other", name: "My curated source" };
  assert.equal(recipeDisplayName(custom, {}), custom.name);
  assert.equal(sortRecipes([custom, collector], collector.id)[0].id, collector.id);
});
