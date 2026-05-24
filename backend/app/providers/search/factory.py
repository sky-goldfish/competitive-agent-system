from app.core.config import get_settings
from app.providers.search.base import SearchProvider
from app.providers.search.duckduckgo import DuckDuckGoSearchProvider
from app.providers.search.mock import MockSearchProvider
from app.providers.search.tavily import TavilySearchProvider


def get_search_provider() -> SearchProvider:
    settings = get_settings()
    if settings.search_provider == "duckduckgo":
        return DuckDuckGoSearchProvider()
    if settings.search_provider == "tavily":
        return TavilySearchProvider()
    if settings.search_provider == "mock":
        return MockSearchProvider()
    if settings.enable_mock_search_fallback:
        return MockSearchProvider()
    raise ValueError(f"Unsupported search provider: {settings.search_provider}")
