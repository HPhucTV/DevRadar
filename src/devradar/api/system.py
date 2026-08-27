from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from devradar.api.common import ApiModel, DataResponse

router = APIRouter(tags=["system"])


class HealthData(BaseModel):
    status: Literal["ok"]


class HealthResponse(BaseModel):
    data: HealthData


class PrivacyData(ApiModel):
    policy_version: Literal["privacy-v3"]
    source_recipes_local_only: Literal[True]
    access_control_bypass_allowed: Literal[False]
    raw_cv_file_retained: Literal[False]
    resume_profile_ttl_hours: Literal[24]
    external_llm_cv_jd_allowed: Literal[False]


PrivacyResponse = DataResponse[PrivacyData]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(data=HealthData(status="ok"))


@router.get("/privacy", response_model=PrivacyResponse)
def get_privacy() -> PrivacyResponse:
    return PrivacyResponse(
        data=PrivacyData(
            policy_version="privacy-v3",
            source_recipes_local_only=True,
            access_control_bypass_allowed=False,
            raw_cv_file_retained=False,
            resume_profile_ttl_hours=24,
            external_llm_cv_jd_allowed=False,
        )
    )
