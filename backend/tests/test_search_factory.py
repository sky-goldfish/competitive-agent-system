import pytest

from app.core.config import get_settings
from app.providers.search.factory import get_search_provider
from app.providers.search.bocha import BochaSearchProvider
from app.providers.search.tavily import TavilySearchProvider


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_factory_selects_tavily_provider(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    get_settings.cache_clear()

    provider = get_search_provider()

    assert provider.name == "tavily"


def test_tavily_requires_api_key_when_fallback_disabled(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        get_search_provider()


def test_tavily_uses_mock_fallback_without_api_key(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "true")
    get_settings.cache_clear()

    provider = get_search_provider()
    results = provider.search("飞书 竞品", limit=2)

    assert provider.name == "tavily"
    assert len(results) == 2
    assert all(result.source_type == "fallback_mock" for result in results)


def test_tavily_maps_response_rows_to_search_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()
    provider = TavilySearchProvider()

    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit, include_raw_content=True: [
            {
                "title": "Example Product",
                "url": "https://example.com/product",
                "content": "Short Tavily content",
                "raw_content": "Long Tavily raw content",
            },
            {
                "title": "Missing URL",
                "content": "This row should be ignored",
            },
        ],
    )

    results = provider.search("example query", limit=5)

    assert len(results) == 1
    assert results[0].title == "Example Product"
    assert results[0].url == "https://example.com/product"
    assert results[0].snippet == "Short Tavily content"
    assert results[0].raw_content == "Long Tavily raw content"
    assert results[0].source_type == "search_result"


def test_tavily_raw_content_falls_back_to_content(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()
    provider = TavilySearchProvider()

    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit, include_raw_content=True: [
            {
                "title": "Example Article",
                "url": "https://example.com/article",
                "content": "Only content is available",
            }
        ],
    )

    results = provider.search("example query", limit=1)

    assert results[0].snippet == "Only content is available"
    assert results[0].raw_content == "Only content is available"


def test_factory_selects_bocha_provider(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "bocha")
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    get_settings.cache_clear()

    provider = get_search_provider()

    assert provider.name == "bocha"


def test_bocha_requires_api_key_when_fallback_disabled(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "bocha")
    monkeypatch.setenv("BOCHA_API_KEY", "")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="BOCHA_API_KEY"):
        get_search_provider()


def test_bocha_uses_mock_fallback_without_api_key(monkeypatch):
    monkeypatch.setenv("SEARCH_PROVIDER", "bocha")
    monkeypatch.setenv("BOCHA_API_KEY", "")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "true")
    get_settings.cache_clear()

    provider = get_search_provider()
    results = provider.search("飞书 竞品", limit=2)

    assert provider.name == "bocha"
    assert len(results) == 2
    assert all(result.source_type == "fallback_mock" for result in results)


def test_bocha_maps_response_rows_to_search_results(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()
    provider = BochaSearchProvider()

    monkeypatch.setattr(
        provider,
        "_request",
        lambda query, limit, include_raw_content=True: [
            {
                "name": "Example Product",
                "url": "https://example.com/product",
                "summary": "Bocha generated summary",
                "snippet": "Bocha snippet",
                "siteName": "Example",
                "datePublished": "2026-05-01",
            },
            {
                "name": "Missing URL",
                "summary": "This row should be ignored",
            },
            {
                "name": "Missing Content",
                "url": "https://example.com/empty",
            },
        ],
    )

    results = provider.search("example query", limit=5)

    assert len(results) == 1
    assert results[0].title == "Example Product"
    assert results[0].url == "https://example.com/product"
    assert results[0].snippet == "Bocha generated summary"
    assert "Example" in results[0].raw_content
    assert results[0].source_type == "search_result"


def test_bocha_falls_back_to_curl_transport(monkeypatch):
    monkeypatch.setenv("BOCHA_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_MOCK_SEARCH_FALLBACK", "false")
    get_settings.cache_clear()
    provider = BochaSearchProvider()

    def fail_urlopen(payload):
        raise RuntimeError("urlopen failed")

    monkeypatch.setattr(provider, "_request_with_urlopen", fail_urlopen)
    monkeypatch.setattr(
        provider,
        "_request_with_curl",
        lambda payload, original_error: {
            "code": 200,
            "data": {
                "webPages": {
                    "value": [
                        {
                            "name": "Curl Result",
                            "url": "https://example.com/curl",
                            "summary": "Returned by curl fallback",
                        }
                    ]
                }
            },
        },
    )

    results = provider.search("example query", limit=1)

    assert len(results) == 1
    assert results[0].title == "Curl Result"
    assert results[0].snippet == "Returned by curl fallback"
