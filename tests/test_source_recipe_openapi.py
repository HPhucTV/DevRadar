from __future__ import annotations

from fastapi.testclient import TestClient

from devradar.main import app


def test_source_recipe_openapi_publishes_only_bounded_resource_contracts() -> None:
    with TestClient(app) as client:
        document = client.get("/api/v1/openapi.json").json()

    expected = {
        "/api/v1/source-catalog": {"get"},
        "/api/v1/source-recipes": {"get", "post"},
        "/api/v1/source-recipes/{recipeId}": {"get", "patch", "delete"},
        "/api/v1/source-recipes/{recipeId}/previews": {"post"},
        "/api/v1/source-recipes/{recipeId}/previews/{previewId}": {"get"},
        "/api/v1/source-recipes/{recipeId}/previews/{previewId}/mapping": {"post"},
        "/api/v1/source-recipes/{recipeId}/crawl-runs": {"get", "post"},
        "/api/v1/source-recipes/{recipeId}/document-imports": {"post"},
    }
    for path, methods in expected.items():
        assert methods <= set(document["paths"][path])

    schemas = document["components"]["schemas"]
    for schema_name in (
        "SourceRecipeCreate",
        "SourceRecipePatch",
        "SourceRecipePreviewRequest",
        "SourceRecipeMappingRequest",
        "SourceRecipeCrawlRequest",
    ):
        assert schemas[schema_name]["additionalProperties"] is False
    serialized_inputs = repr(
        {
            name: schemas[name]
            for name in (
                "SourceRecipePreviewRequest",
                "SourceRecipeMappingRequest",
                "SourceRecipeCrawlRequest",
            )
        }
    ).casefold()
    for forbidden in ("headers", "cookies", "proxy", "code", "selector", "outboundurl"):
        assert forbidden not in serialized_inputs
    screenshot = schemas["SourceRecipePreviewData"]["properties"]["screenshotDataUrl"]
    assert screenshot["anyOf"][0]["maxLength"] <= 2_100_000
    preview_properties = schemas["SourceRecipePreviewData"]["properties"]
    assert preview_properties["proposedHosts"]["items"]["type"] == "string"
    assert preview_properties["proposedPathPrefixes"]["items"]["type"] == "string"

    import_operation = document["paths"]["/api/v1/source-recipes/{recipeId}/document-imports"][
        "post"
    ]
    multipart = import_operation["requestBody"]["content"]["multipart/form-data"]["schema"]
    assert multipart["required"] == ["file"]
    assert set(multipart["properties"]) == {"file"}
    assert multipart["additionalProperties"] is False
    idempotency = next(
        parameter
        for parameter in import_operation["parameters"]
        if parameter["name"] == "Idempotency-Key"
    )
    assert idempotency["required"] is True
    assert idempotency["schema"]["minLength"] == 8
    assert idempotency["schema"]["maxLength"] == 128
