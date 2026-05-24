from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        """Extract a structured requirement summary."""
        ...

    def understand_target(self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]) -> dict[str, Any]:
        """Summarize target product or product idea before competitor discovery."""
        ...

    def extract_competitors(
        self,
        requirement: dict[str, Any],
        target_understanding: dict[str, Any],
        search_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Extract competitor candidates from real search results."""
        ...

    def analyze_competitor(self, competitor: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, Any]:
        """Create structured competitor analysis."""
        ...

    def generate_report(self, run: dict[str, Any], analyses: list[dict[str, Any]], sources: list[dict[str, Any]]) -> dict[str, str]:
        """Generate a markdown report."""
        ...
