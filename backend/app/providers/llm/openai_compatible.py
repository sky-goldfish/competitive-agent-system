from openai import OpenAI

from app.core.config import get_settings
from app.providers.llm.ark import ArkLLMProvider
from app.providers.llm.mock import MockLLMProvider


class OpenAICompatibleLLMProvider(ArkLLMProvider):
    """LLM provider for OpenAI Chat Completions-compatible endpoints."""

    name = "openai"

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai.")
        if not settings.openai_model:
            raise ValueError("OPENAI_MODEL is required when LLM_PROVIDER=openai.")

        self.model = settings.openai_model
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self.temperature = settings.openai_temperature
        self.fallback = MockLLMProvider()
