from typing import Any, Protocol


class LLMProvider(Protocol):
    name: str

    def understand_requirement(self, user_requirement: str) -> dict[str, Any]:
        """Extract a structured requirement summary."""
        ...

    def extract_focus_profile(
        self, user_requirement: str, requirement: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract user-specific priorities and optional clarification question."""
        ...

    def understand_target(
        self, requirement: dict[str, Any], target_search_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
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

    def analyze_competitor(
        self, competitor: dict[str, Any], evidence: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Create structured competitor analysis."""
        ...

    def extract_evidence_from_source(
        self,
        source: dict[str, Any],
        query_item: dict[str, Any],
        competitor: dict[str, Any],
        requirement: dict[str, Any],
    ) -> dict[str, Any]:
        """Extract 0..N structured evidence items from one source."""
        ...

    def generate_report(
        self,
        run: dict[str, Any],
        analyses: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Generate a markdown report."""
        ...

    def qa_check_report(
        self,
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Quality-check structured analyses and their supporting evidence. Returns structured QA verdict."""
        ...

    def qa_verify_issues(
        self,
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        open_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Check whether previously open QA issues have been resolved."""
        ...

    def classify_chat_intent(
        self,
        user_message: str,
        report_summary: str,
        chat_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Classify user's chat intent as report_edit or report_redo."""
        ...

    def edit_report_markdown(
        self,
        report_markdown: str,
        user_message: str,
        context: str,
    ) -> str:
        """Edit a report markdown based on user's modification request."""
        ...

    def generate_chat_queries(
        self,
        user_message: str,
        report_summary: str,
        existing_competitors: list[str],
    ) -> dict[str, Any]:
        """Generate search queries and analysis guidance for report_redo."""
        ...

    def classify_revision_intent(
        self,
        user_message: str,
        current_report: dict[str, Any],
        chat_history: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Classify revision request and decide whether additional research is needed."""
        ...

    def generate_revision_search_plan(
        self,
        user_message: str,
        current_report: dict[str, Any],
        competitors: list[dict[str, Any]],
        existing_sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate targeted search queries for a revision request."""
        ...

    def generate_revision_plan(
        self,
        user_message: str,
        current_report: dict[str, Any],
        analyses: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        new_sources: list[dict[str, Any]],
        intent_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Plan which report sections and structure should change."""
        ...

    def revise_report_with_plan(
        self,
        current_report: dict[str, Any],
        revision_plan: dict[str, Any],
        citation_bundle: list[dict[str, Any]],
        sources: list[dict[str, Any]],
    ) -> dict[str, str]:
        """Generate a revised report from a structured revision plan."""
        ...

    def generate_revision_summary(
        self,
        user_message: str,
        revision_plan: dict[str, Any],
        new_report: dict[str, Any],
    ) -> str:
        """Summarize what changed in the revised report."""
        ...
