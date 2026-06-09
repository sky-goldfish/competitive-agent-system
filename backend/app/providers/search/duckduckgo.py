from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
import logging
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider
from app.services import call_tracer

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
        started_at = datetime.utcnow()
        future: Future = _EXECUTOR.submit(self._do_search, query, limit)
        try:
            rows = future.result(timeout=15)
        except Exception as exc:
            future.cancel()
            if isinstance(exc, (TimeoutError, TimeoutException)):
                logger.warning("DDGS search timed out: %s", query[:60])
            if not self.use_fallback:
                call_tracer.record_search_call(
                    provider=self.name,
                    input_data={"query": query, "limit": limit},
                    output_data={"error": "timeout" if isinstance(exc, (TimeoutError, TimeoutException)) else str(exc)},
                    duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                    started_at=started_at,
                    status="failed",
                    error="Search timed out" if isinstance(exc, (TimeoutError, TimeoutException)) else str(exc),
                )
                if isinstance(exc, (TimeoutError, TimeoutException)):
                    raise TimeoutError(f"Search timed out for query: {query}") from exc
                raise
            fallback_results = [
                SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
                for result in self.fallback.search(
                    query, limit=limit, include_raw_content=include_raw_content
                )
            ]
            call_tracer.record_search_call(
                provider=self.name,
                input_data={"query": query, "limit": limit},
                output_data={
                    "results": [
                        {"title": r.title, "url": r.url, "snippet": r.snippet[:200]}
                        for r in fallback_results
                    ],
                    "count": len(fallback_results),
                    "fallback": True,
                },
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                started_at=started_at,
            )
            return fallback_results

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
            call_tracer.record_search_call(
                provider=self.name,
                input_data={"query": query, "limit": limit},
                output_data={
                    "results": [
                        {"title": r.title, "url": r.url, "snippet": r.snippet[:200]}
                        for r in results
                    ],
                    "count": len(results),
                },
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                started_at=started_at,
            )
            return results[:limit]
        if not self.use_fallback:
            call_tracer.record_search_call(
                provider=self.name,
                input_data={"query": query, "limit": limit},
                output_data={"error": "no_results"},
                duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
                started_at=started_at,
                status="failed",
                error=f"No search results for query: {query}",
            )
            raise RuntimeError(f"No search results for query: {query}")
        fallback_results = [
            SearchResult(**{**result.__dict__, "source_type": "fallback_mock"})
            for result in self.fallback.search(
                query, limit=limit, include_raw_content=include_raw_content
            )
        ]
        call_tracer.record_search_call(
            provider=self.name,
            input_data={"query": query, "limit": limit},
            output_data={
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet[:200]}
                    for r in fallback_results
                ],
                "count": len(fallback_results),
                "fallback": True,
            },
            duration_ms=int((datetime.utcnow() - started_at).total_seconds() * 1000),
            started_at=started_at,
        )
        return fallback_results

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
