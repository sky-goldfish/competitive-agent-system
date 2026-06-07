from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
import signal
import logging

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider

logger = logging.getLogger(__name__)


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def __init__(self) -> None:
        self.fallback = MockSearchProvider()
        self.use_fallback = get_settings().enable_mock_search_fallback
        self.backend = (
            getattr(get_settings(), "ddgs_backend", None) or "yandex,bing,mojeek"
        )

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            signal.alarm(15)
            rows = list(
                DDGS(timeout=10).text(
                    query,
                    max_results=limit,
                    backend=self.backend,
                    region="wt-wt",
                    safesearch="moderate",
                )
            )
            signal.alarm(0)
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
        except (TimeoutError, TimeoutException):
            signal.alarm(0)
            logger.warning("DDGS search timed out: %s", query[:60])
            if not self.use_fallback:
                raise
        except DDGSException:
            signal.alarm(0)
            if not self.use_fallback:
                raise
        except Exception:
            signal.alarm(0)
            if not self.use_fallback:
                raise
        return [
            SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
            for result in self.fallback.search(query, limit=limit)
        ]
