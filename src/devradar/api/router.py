from fastapi import APIRouter

from devradar.api.crawl_runs import router as crawl_runs_router
from devradar.api.jobs import router as jobs_router
from devradar.api.sources import router as sources_router
from devradar.api.system import router as system_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router)
api_router.include_router(jobs_router)
api_router.include_router(sources_router)
api_router.include_router(crawl_runs_router)
