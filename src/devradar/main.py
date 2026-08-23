from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from devradar.api.errors import install_error_handlers
from devradar.api.router import api_router
from devradar.auth.service import allowed_origins
from devradar.platform.observability import configure_structured_logging
from devradar.platform.security_config import validate_security_configuration

configure_structured_logging()
validate_security_configuration()
app = FastAPI(
    title="DevRadar API",
    version="0.1.0",
    openapi_url="/api/v1/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins()),
    allow_credentials=True,
    allow_methods=["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST"],
    allow_headers=["Accept", "Content-Type", "Idempotency-Key", "X-DevRadar-CSRF"],
    expose_headers=["Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-Request-ID"],
    max_age=600,
)
install_error_handlers(app)
app.include_router(api_router)
