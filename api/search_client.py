"""api/search_client.py

Vertex AI Search (Discovery Engine) client with ACL-aware retrieval.

Builds filter expressions from caller's group memberships (resolved by authz.py)
and passes them to the Vertex AI Search query so users only see documents
they are authorised to access.

Fixes Issue #1: IAM/ACL access-aware retrieval filter.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "my-gcp-project")
LOCATION = os.environ.get("LOCATION", "us-central1")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "policy-docs")
DATA_STORE_LOCATION = os.environ.get("DATA_STORE_LOCATION", "global")


class VertexSearchClient:
    """Thin wrapper around Discovery Engine SearchServiceClient.

    Supports ACL filter injection so that results are restricted to
    documents whose acl_groups / acl_users metadata overlaps with the
    caller's identity.
    """

    def __init__(self) -> None:
        self._client = self._build_client()
        self._serving_config = (
            f"projects/{PROJECT_ID}/locations/{DATA_STORE_LOCATION}"
            f"/collections/default_collection/dataStores/{DATA_STORE_ID}"
            f"/servingConfigs/default_config"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        acl_filter: Optional[str] = None,
        page_size: int = 5,
        summary_result_count: int = 5,
    ) -> Dict[str, Any]:
        """Execute a grounded search query against Vertex AI Search.

        Args:
            query: Natural-language question from the user.
            acl_filter: Optional Vertex AI Search filter expression built
                by :func:`api.authz.build_acl_filter`. When supplied, only
                documents matching the filter are returned.
            page_size: Number of result documents to retrieve.
            summary_result_count: Number of docs included in the LLM summary.

        Returns:
            Raw Discovery Engine response dict (or stub dict when client
            is not initialised).
        """
        if self._client is None:
            return self._stub_response(query, acl_filter)

        try:
            from google.cloud import discoveryengine_v1beta as discoveryengine  # type: ignore

            content_spec = discoveryengine.SearchRequest.ContentSearchSpec(
                summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                    summary_result_count=summary_result_count,
                    include_citations=True,
                    ignore_adversarial_query=True,
                    model_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec.ModelSpec(
                        version="gemini-2.0-flash-001"
                    ),
                ),
                extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_answer_count=3,
                ),
            )

            request = discoveryengine.SearchRequest(
                serving_config=self._serving_config,
                query=query,
                page_size=page_size,
                content_search_spec=content_spec,
                filter=acl_filter or "",
            )

            response = self._client.search(request)
            logger.info(
                "Vertex AI Search returned %d results for query=%r filter=%r",
                len(list(response.results)),
                query[:80],
                acl_filter,
            )
            return {"response": response, "acl_filter_applied": acl_filter}

        except Exception as exc:  # noqa: BLE001
            logger.exception("Vertex AI Search error: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        """Instantiate the Discovery Engine SearchServiceClient."""
        try:
            from google.cloud import discoveryengine_v1beta as discoveryengine  # type: ignore

            client = discoveryengine.SearchServiceClient()
            logger.info("DiscoveryEngine SearchServiceClient initialised.")
            return client
        except ImportError:
            logger.warning(
                "google-cloud-discoveryengine not installed; running in stub mode."
            )
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not init DiscoveryEngine client: %s", exc)
            return None

    @staticmethod
    def _stub_response(query: str, acl_filter: Optional[str]) -> Dict[str, Any]:
        """Return a deterministic stub response for local development."""
        logger.info(
            "[STUB] search_client: query=%r acl_filter=%r", query[:80], acl_filter
        )
        stub_answer = (
            f"[STUB] Grounded answer for: {query} "
            "[source: stub-section-1 | https://example.com/policy#section-1]"
        )
        return {
            "answer": stub_answer,
            "grounding_score": 0.0,
            "acl_filter_applied": acl_filter,
            "results": [
                {
                    "section_id": "stub-section-1",
                    "doc_url": "https://example.com/policy#section-1",
                    "snippet": "Stub snippet for local development.",
                    "modified_at": "2026-01-01T00:00:00Z",
                }
            ],
        }


# Module-level singleton — reuse across requests (client is thread-safe)
_client: Optional[VertexSearchClient] = None


def get_search_client() -> VertexSearchClient:
    """Return the module-level VertexSearchClient singleton."""
    global _client
    if _client is None:
        _client = VertexSearchClient()
    return _client
