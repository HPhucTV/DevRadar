from uuid import UUID

from devradar.source_recipes.identity import recipe_code


def test_recipe_code_is_deterministic_and_not_a_secret() -> None:
    assert recipe_code(UUID("f1fe63e0-61dc-40b7-93c2-72c670c28155")) == "RCP-F1FE63E0"
