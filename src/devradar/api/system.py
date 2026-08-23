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
    policy_version: Literal["privacy-v1"]
    raw_cv_file_retained: Literal[False]
    resume_profile_ttl_hours: Literal[24]
    owner_deletion_supported: Literal[True]
    external_llm_cv_jd_allowed: Literal[False]
    deterministic_extraction_first: Literal[True]
    source_allowlist_only: Literal[True]
    permission_required_source_keys: tuple[Literal["geocomply-lever"], ...]


PrivacyResponse = DataResponse[PrivacyData]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(data=HealthData(status="ok"))


@router.get("/privacy", response_model=PrivacyResponse)
def get_privacy() -> PrivacyResponse:
    return PrivacyResponse(
        data=PrivacyData(
            policy_version="privacy-v1",
            raw_cv_file_retained=False,
            resume_profile_ttl_hours=24,
            owner_deletion_supported=True,
            external_llm_cv_jd_allowed=False,
            deterministic_extraction_first=True,
            source_allowlist_only=True,
            permission_required_source_keys=("geocomply-lever",),
        )
    )
