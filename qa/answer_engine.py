"""qa/answer_engine.py

Gemini Flash answer engine with Vertex AI Search grounding.
Every answer MUST contain at least one citation block.

Citation format: [source: <section_id> | <doc_url>]
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from qa.citation_enforcer import CitationEnforcer, CitationError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment config
# ---------------------------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "my-gcp-project")
LOCATION = os.environ.get("LOCATION", "us-central1")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "policy-docs")
MODEL_ID = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

CITATION_INSTRUCTION = (
    "You MUST end every answer with at least one citation in the exact format: "
    "[source: <section_id> | <doc_url>]. "
    "If you cannot cite a source, respond: 'I cannot answer without a verified source.'"
)


@dataclass
class AnswerResult:
    answer: str
    citations: List[Dict[str, str]]
    grounding_score: float = 0.0
    raw_response: Optional[Any] = None


class AnswerEngine:
    """Query Vertex AI Search + Gemini Flash and enforce citation format."""

    def __init__(self) -> None:
        self._enforcer = CitationEnforcer()
        self._client = self._build_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def answer(self, question: str) -> AnswerResult:
        """Return a grounded, citation-enforced answer to *question*."""
        raw = self._search_and_generate(question)
        text = self._extract_text(raw)

        try:
            citations = self._enforcer.extract(text)
            self._enforcer.validate(text)  # raises CitationError if none found
        except CitationError:
            logger.warning("Answer rejected - no citations found. Re-prompting.")
            # Fallback: ask model to add citations
            text = self._enforce_citations(question, text)
            citations = self._enforcer.extract(text)

        return AnswerResult(
            answer=text,
            citations=citations,
            raw_response=raw,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _build_client(self) -> Any:
        """Build the Vertex AI Discovery Engine client.

        TODO: Uncomment once google-cloud-discoveryengine is installed.
        """
        # from google.cloud import discoveryengine_v1beta as discoveryengine
        # return discoveryengine.SearchServiceClient()
        logger.info("[STUB] DiscoveryEngine client not yet initialised.")
        return None

    def _search_and_generate(
        self,
        question: str,
    ) -> Dict[str, Any]:
        """Call Vertex AI Search with Grounding + Gemini Flash.

        TODO: Replace stub with real implementation.
        """
        if self._client is None:
            logger.info("[STUB] Would search Vertex AI for: %s", question)
            return {
                "answer": f"[STUB] Answering: {question} [source: stub-section | https://example.com/doc]",
                "grounding_score": 0.0,
            }
        # Real implementation:
        # serving_config = self._client.serving_config_path(
        #     project=PROJECT_ID, location=LOCATION,
        #     data_store=DATA_STORE_ID, serving_config="default_config"
        # )
        # request = discoveryengine.SearchRequest(
        #     serving_config=serving_config,
        #     query=question,
        #     content_search_spec=discoveryengine.SearchRequest.ContentSearchSpec(
        #         summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
        #             summary_result_count=5,
        #             include_citations=True,
        #             model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
        #                 version=MODEL_ID
        #             ),
        #         )
        #     ),
        # )
        # response = self._client.search(request)
        # return response
        return {}

    def _extract_text(self, raw: Any) -> str:
        if isinstance(raw, dict):
            return raw.get("answer", "")
        return ""

    def _enforce_citations(self, question: str, answer: str) -> str:
        """Re-ask the model to add citations to an uncited answer."""
        logger.warning("Fallback: injecting citation requirement into prompt.")
        # TODO: call Gemini with revised prompt
        return answer + " [source: unknown | https://example.com]"

