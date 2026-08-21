from fastapi import FastAPI

from devradar.api.router import api_router

app = FastAPI(
    title="DevRadar API",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
)
app.include_router(api_router)
