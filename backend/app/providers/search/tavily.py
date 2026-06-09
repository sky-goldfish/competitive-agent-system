import json
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider


class TavilySearchProvider:
    name = "tavily"
    endpoint = "https://api.tavily.com/search"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.tavily_api_key
        self.use_fallback = settings.enable_mock_search_fallback
        self.fallback = MockSearchProvider()
        if not self.api_key and not self.use_fallback:
            raise ValueError(
                "TAVILY_API_KEY is required when SEARCH_PROVIDER=tavily and mock fallback is disabled."
            )

    def search(
        self, query: str, *, limit: int = 5, include_raw_content: bool = True
    ) -> list[SearchResult]:
        try:
            if not self.api_key:
                raise ValueError(
                    "TAVILY_API_KEY is required when SEARCH_PROVIDER=tavily."
                )
            results = self._to_search_results(
                self._request(query, limit, include_raw_content=include_raw_content)
            )
            if results:
                return results[:limit]
            if not self.use_fallback:
                raise RuntimeError(f"No Tavily search results for query: {query}")
        except Exception:
            if not self.use_fallback:
                raise
        return self._fallback_results(query, limit)

    def _request(
        self, query: str, limit: int, *, include_raw_content: bool = True
    ) -> list[dict]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": limit,
            "include_raw_content": include_raw_content,
        }
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
        data = json.loads(body)
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    @staticmethod
    def _to_search_results(rows: list[dict]) -> list[SearchResult]:
        results = []
        for row in rows:
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            content = str(row.get("content") or "")
            raw_content = row.get("raw_content") or content
            results.append(
                SearchResult(
                    title=str(row.get("title") or url or "未命名来源"),
                    url=url,
                    snippet=content,
                    raw_content=str(raw_content or ""),
                )
            )
        return results

    def _fallback_results(self, query: str, limit: int) -> list[SearchResult]:
        return [
            SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
            for result in self.fallback.search(query, limit=limit)
        ]
