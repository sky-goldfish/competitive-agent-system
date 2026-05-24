from app.core.config import get_settings
from app.providers.llm.ark import ArkLLMProvider
from app.providers.llm.base import LLMProvider
from app.providers.llm.mock import MockLLMProvider


def get_llm_provider() -> LLMProvider:
    settings = get_settings()
    if settings.llm_provider == "ark":
        return ArkLLMProvider()
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    return MockLLMProvider()
