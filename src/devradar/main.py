from fastapi import FastAPI

from devradar.api.errors import install_error_handlers
from devradar.api.router import api_router

app = FastAPI(
    title="DevRadar API",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
)
install_error_handlers(app)
app.include_router(api_router)
