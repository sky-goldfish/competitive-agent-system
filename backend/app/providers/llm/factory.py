from app.core.config import get_settings
from app.providers.llm.ark import ArkLLMProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockLLMProvider
from app.providers.llm.openai_compatible import OpenAICompatibleLLMProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "ark":
        return ArkLLMProvider()
    if settings.llm_provider in {"openai", "openai_compatible", "openai-compatible"}:
        return OpenAICompatibleLLMProvider()
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    return MockLLMProvider()
