from pathlib import Path

from dotenv import dotenv_values

from app.core.config import get_settings
from app.schemas.api_settings import (
    APISettingsResponse,
    APISettingsUpdate,
    LLMSettingsResponse,
    SearchSettingsResponse,
    SecretStatus,
)

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"


def read_api_settings() -> APISettingsResponse:
    settings = get_settings()
    llm_provider = _normalize_llm_provider(settings.llm_provider)
    search_provider = _normalize_search_provider(settings.search_provider)
    return APISettingsResponse(
        llm=LLMSettingsResponse(
            provider=llm_provider,
            effective_provider=_effective_llm_provider(llm_provider, settings.ark_api_key, settings.openai_api_key),
            ark_api_key=_secret_status(settings.ark_api_key),
            ark_endpoint_id=settings.ark_endpoint_id or "",
            ark_model=settings.ark_model or "",
            ark_base_url=settings.ark_base_url or "",
            openai_api_key=_secret_status(settings.openai_api_key),
            openai_model=settings.openai_model or "",
            openai_base_url=settings.openai_base_url or "",
            openai_temperature=settings.openai_temperature,
        ),
        search=SearchSettingsResponse(
            provider=search_provider,
            effective_provider=_effective_search_provider(
                search_provider,
                settings.tavily_api_key,
                settings.bocha_api_key,
            ),
            tavily_api_key=_secret_status(settings.tavily_api_key),
            bocha_api_key=_secret_status(settings.bocha_api_key),
            enable_mock_search_fallback=settings.enable_mock_search_fallback,
        ),
        env_path=str(ENV_PATH),
    )


def update_api_settings(payload: APISettingsUpdate) -> APISettingsResponse:
    llm_provider = _normalize_llm_provider(payload.llm.provider)
    search_provider = _normalize_search_provider(payload.search.provider)
    ark_key = payload.llm.ark_api_key.strip()
    openai_key = payload.llm.openai_api_key.strip()
    tavily_key = payload.search.tavily_api_key.strip()
    bocha_key = payload.search.bocha_api_key.strip()

    if llm_provider == "ark" and not ark_key:
        llm_provider = "mock"
    if llm_provider == "openai" and not openai_key:
        llm_provider = "mock"
    if search_provider == "tavily" and not tavily_key:
        search_provider = "mock"
    if search_provider == "bocha" and not bocha_key:
        search_provider = "mock"

    env_values = _read_env_values()
    env_values.update(
        {
            "LLM_PROVIDER": llm_provider,
            "ARK_API_KEY": ark_key if llm_provider == "ark" else "",
            "ARK_ENDPOINT_ID": payload.llm.ark_endpoint_id.strip(),
            "ARK_MODEL": payload.llm.ark_model.strip() or "doubao-seed-2-0-lite",
            "ARK_BASE_URL": payload.llm.ark_base_url.strip()
            or "https://ark.cn-beijing.volces.com/api/v3",
            "OPENAI_API_KEY": openai_key if llm_provider == "openai" else "",
            "OPENAI_MODEL": payload.llm.openai_model.strip(),
            "OPENAI_BASE_URL": payload.llm.openai_base_url.strip()
            or "https://api.openai.com/v1",
            "OPENAI_TEMPERATURE": ""
            if payload.llm.openai_temperature is None
            else str(payload.llm.openai_temperature),
            "SEARCH_PROVIDER": search_provider,
            "TAVILY_API_KEY": tavily_key if search_provider == "tavily" else "",
            "BOCHA_API_KEY": bocha_key if search_provider == "bocha" else "",
            "ENABLE_MOCK_SEARCH_FALLBACK": str(payload.search.enable_mock_search_fallback).lower(),
        }
    )
    _write_env_values(env_values)
    get_settings.cache_clear()
    return read_api_settings()


def _read_env_values() -> dict[str, str]:
    if not ENV_PATH.exists():
        return {}
    return {
        key: value or ""
        for key, value in dotenv_values(ENV_PATH).items()
        if key is not None
    }


def _write_env_values(values: dict[str, str]) -> None:
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={_quote_env_value(value)}\n" for key, value in values.items()]
    ENV_PATH.write_text("".join(lines), encoding="utf-8")


def _quote_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(char.isspace() or char in {'"', "'", "#", "="} for char in value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _secret_status(value: str | None) -> SecretStatus:
    if not value:
        return SecretStatus()
    return SecretStatus(configured=True, masked=_mask_secret(value))


def _mask_secret(value: str) -> str:
    if len(value) <= 10:
        return f"{value[:2]}****{value[-2:]}"
    return f"{value[:6]}...{value[-4:]}"


def _normalize_llm_provider(provider: str) -> str:
    normalized = provider.strip().lower().replace("-", "_")
    if normalized in {"ark", "openai", "mock"}:
        return normalized
    if normalized == "openai_compatible":
        return "openai"
    return "mock"


def _normalize_search_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized in {"tavily", "bocha", "mock"}:
        return normalized
    return "mock"


def _effective_llm_provider(provider: str, ark_key: str | None, openai_key: str | None) -> str:
    if provider == "ark" and ark_key:
        return "ark"
    if provider == "openai" and openai_key:
        return "openai"
    return "mock"


def _effective_search_provider(provider: str, tavily_key: str | None, bocha_key: str | None) -> str:
    if provider == "tavily" and tavily_key:
        return "tavily"
    if provider == "bocha" and bocha_key:
        return "bocha"
    return "mock"
