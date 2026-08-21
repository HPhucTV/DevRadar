from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["system"])


class HealthData(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    data: HealthData


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(data=HealthData(status="ok"))
