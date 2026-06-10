from pydantic import BaseModel, Field


class SecretStatus(BaseModel):
    configured: bool = False
    masked: str = ""


class LLMSettingsResponse(BaseModel):
    provider: str
    effective_provider: str
    ark_api_key: SecretStatus
    ark_endpoint_id: str = ""
    ark_model: str = ""
    ark_base_url: str = ""
    openai_api_key: SecretStatus
    openai_model: str = ""
    openai_base_url: str = ""
    openai_temperature: float | None = None


class SearchSettingsResponse(BaseModel):
    provider: str
    effective_provider: str
    tavily_api_key: SecretStatus
    bocha_api_key: SecretStatus
    enable_mock_search_fallback: bool


class APISettingsResponse(BaseModel):
    llm: LLMSettingsResponse
    search: SearchSettingsResponse
    env_path: str


class LLMSettingsUpdate(BaseModel):
    provider: str = "mock"
    ark_api_key: str = ""
    ark_endpoint_id: str = ""
    ark_model: str = "doubao-seed-2-0-lite"
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_temperature: float | None = Field(default=None, ge=0, le=2)


class SearchSettingsUpdate(BaseModel):
    provider: str = "mock"
    tavily_api_key: str = ""
    bocha_api_key: str = ""
    enable_mock_search_fallback: bool = True


class APISettingsUpdate(BaseModel):
    llm: LLMSettingsUpdate
    search: SearchSettingsUpdate
