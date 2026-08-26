from uuid import UUID


def recipe_code(recipe_id: UUID) -> str:
    return f"RCP-{recipe_id.hex[:8].upper()}"
