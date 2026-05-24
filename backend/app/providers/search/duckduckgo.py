from ddgs import DDGS

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self) -> None:
        self.fallback = MockSearchProvider()
        self.use_fallback = get_settings().enable_mock_search_fallback

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            rows = list(DDGS().text(query, max_results=limit, region="wt-wt", safesearch="moderate"))
            results = [
                SearchResult(
                    title=row.get("title") or "未命名来源",
                    url=row.get("href") or row.get("url") or "",
                    snippet=row.get("body") or "",
                    raw_content=row.get("body") or "",
                )
                for row in rows
                if row.get("href") or row.get("url")
            ]
            if results:
                return results[:limit]
            if not self.use_fallback:
                raise RuntimeError(f"No search results for query: {query}")
        except Exception:
            if not self.use_fallback:
                raise
        return [SearchResult(**{**result.__dict__, "source_type": "fallback_mock"}) for result in self.fallback.search(query, limit=limit)]
