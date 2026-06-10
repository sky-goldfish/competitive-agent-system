from fastapi import APIRouter

from app.schemas.api_settings import APISettingsResponse, APISettingsUpdate
from app.services.api_settings_service import read_api_settings, update_api_settings

router = APIRouter(prefix="/settings/api", tags=["settings"])


@router.get("", response_model=APISettingsResponse)
def get_api_settings() -> APISettingsResponse:
    return read_api_settings()


@router.put("", response_model=APISettingsResponse)
def save_api_settings(payload: APISettingsUpdate) -> APISettingsResponse:
    return update_api_settings(payload)
