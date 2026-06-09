from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
import logging
from concurrent.futures import Future, ThreadPoolExecutor

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ddgs")


class _SearchTimeout(Exception):
    pass


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self) -> None:
        self.fallback = MockSearchProvider()
        self.use_fallback = get_settings().enable_mock_search_fallback
        self.backend = (
            getattr(get_settings(), "ddgs_backend", None) or "yandex,bing,mojeek"
        )

    def search(
        self, query: str, *, limit: int = 5, include_raw_content: bool = True
    ) -> list[SearchResult]:
        future: Future = _EXECUTOR.submit(self._do_search, query, limit)
        try:
            rows = future.result(timeout=15)
        except Exception as exc:
            future.cancel()
            if isinstance(exc, (TimeoutError, TimeoutException)):
                logger.warning("DDGS search timed out: %s", query[:60])
            if not self.use_fallback:
                if isinstance(exc, (TimeoutError, TimeoutException)):
                    raise TimeoutError(f"Search timed out for query: {query}") from exc
                raise
            return [
                SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
                for result in self.fallback.search(query, limit=limit)
            ]

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
        return [
            SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
            for result in self.fallback.search(query, limit=limit)
        ]

    def _do_search(self, query: str, limit: int) -> list[dict]:
        try:
            return list(
                DDGS(timeout=10).text(
                    query,
                    max_results=limit,
                    backend=self.backend,
                    region="wt-wt",
                    safesearch="moderate",
                )
            )
        except (TimeoutException, DDGSException):
            raise
        except Exception:
            return []
