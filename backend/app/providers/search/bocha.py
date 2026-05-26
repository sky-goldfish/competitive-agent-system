import json
import subprocess
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.providers.search.base import SearchResult
from app.providers.search.mock import MockSearchProvider


class BochaSearchProvider:
    name = "bocha"
    endpoint = "https://api.bocha.cn/v1/web-search"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.bocha_api_key
        self.use_fallback = settings.enable_mock_search_fallback
        self.fallback = MockSearchProvider()
        if not self.api_key and not self.use_fallback:
            raise ValueError("BOCHA_API_KEY is required when SEARCH_PROVIDER=bocha and mock fallback is disabled.")

    def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        try:
            if not self.api_key:
                raise ValueError("BOCHA_API_KEY is required when SEARCH_PROVIDER=bocha.")
            results = self._to_search_results(self._request(query, limit))
            if results:
                return results[:limit]
            if not self.use_fallback:
                raise RuntimeError(f"No Bocha search results for query: {query}")
        except Exception:
            if not self.use_fallback:
                raise
        return self._fallback_results(query, limit)

    def _request(self, query: str, limit: int) -> list[dict]:
        payload = {
            "query": query,
            "summary": True,
            "count": limit,
            "freshness": "noLimit",
        }
        try:
            data = self._request_with_urlopen(payload)
        except Exception as exc:
            data = self._request_with_curl(payload, exc)
        if data.get("code") != 200:
            raise RuntimeError(f"Bocha API returned error: {data.get('msg') or 'unknown error'}")
        webpages = data.get("data", {}).get("webPages", {}).get("value", [])
        return webpages if isinstance(webpages, list) else []

    def _request_with_urlopen(self, payload: dict) -> dict:
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _request_with_curl(self, payload: dict, original_error: Exception) -> dict:
        command = [
            "curl",
            "-sS",
            "--fail-with-body",
            "-X",
            "POST",
            self.endpoint,
            "-H",
            f"Authorization: Bearer {self.api_key}",
            "-H",
            "Content-Type: application/json",
            "--data-binary",
            "@-",
        ]
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(payload).encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
                check=False,
            )
        except Exception as curl_error:
            raise RuntimeError(f"Bocha request failed: {original_error}") from curl_error
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")[:300]
            stdout = completed.stdout.decode("utf-8", errors="replace")[:300]
            detail = stderr or stdout or f"curl exit code {completed.returncode}"
            raise RuntimeError(f"Bocha request failed after urlopen error {original_error}: {detail}")
        return json.loads(completed.stdout.decode("utf-8"))

    @staticmethod
    def _to_search_results(rows: list[dict]) -> list[SearchResult]:
        results = []
        for row in rows:
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            summary = str(row.get("summary") or "")
            snippet = str(row.get("snippet") or "")
            content = summary or snippet
            if not content:
                continue
            site_name = str(row.get("siteName") or "").strip()
            date = str(row.get("datePublished") or row.get("dateLastCrawled") or "").strip()
            metadata = " ".join(item for item in [site_name, date] if item)
            raw_content = content if not metadata else f"{content}\n\n来源信息：{metadata}"
            results.append(
                SearchResult(
                    title=str(row.get("name") or row.get("title") or url or "未命名来源"),
                    url=url,
                    snippet=content,
                    raw_content=raw_content,
                )
            )
        return results

    def _fallback_results(self, query: str, limit: int) -> list[SearchResult]:
        return [SearchResult(**{**result.__dict__, "source_type": "fallback_mock"}) for result in self.fallback.search(query, limit=limit)]
