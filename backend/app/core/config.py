from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./competitive_agent.db"
    llm_provider: str = "mock"
    ark_api_key: str | None = None
    ark_endpoint_id: str | None = None
    ark_model: str = "doubao-seed-2-0-lite"
    ark_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_temperature: float | None = None
    search_provider: str = "mock"
    tavily_api_key: str | None = None
    bocha_api_key: str | None = None
    enable_mock_search_fallback: bool = True
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
