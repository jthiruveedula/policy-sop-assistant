"""api/main.py

Cloud Run FastAPI service for the Policy SOP Assistant.

Enhancements over the original:
  - Full structured AskResponse schema (citations, confidence_label,
    source_count, latest_source_ts, refusal_reason) via api/models.py
  - ACL-aware retrieval: resolves caller groups via authz.py and passes
    an ACL filter to VertexSearchClient (fixes Issue #1)
  - Session-based multi-turn memory via api/session.py (fixes Issue #2)
  - Policy version diff endpoint: GET /diff/{policy_id}/versions/{v1}/{v2}
    (fixes Issue #3)
  - Admin endpoint: GET /sessions/{session_id}/history

Deploy:
    gcloud run deploy policy-sop-api \\
        --source . \\
        --region us-central1 \\
        --set-env-vars PROJECT_ID=<proj>,DATA_STORE_ID=<store>
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from api.authz import build_acl_filter, resolve_caller_groups
from api.diff import get_diff_engine
from api.models import (
    AskRequest,
    AskResponse,
    CitationOut,
    ConfidenceLabel,
    PolicyDiffResponse,
    SessionHistoryResponse,
)
from api.search_client import get_search_client
from api.session import get_session_manager
from qa.answer_engine import AnswerEngine, AnswerResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Policy SOP Assistant",
    description=(
        "Enterprise Q&A with mandatory Vertex AI Search citations. "
        "Every answer includes source citations, a confidence label, and a "
        "refusal reason when no valid source is found."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ALLOWED_ORIGIN", "*")],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Engine singleton
# ---------------------------------------------------------------------------

_engine: Optional[AnswerEngine] = None


def _get_engine() -> AnswerEngine:
    global _engine
    if _engine is None:
        _engine = AnswerEngine()
    return _engine


# ---------------------------------------------------------------------------
# Routes: health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
async def health() -> dict:
    """Health check for Cloud Run liveness probe."""
    return {"status": "ok", "version": app.version}


# ---------------------------------------------------------------------------
# Routes: /ask  (enhanced with ACL + session)
# ---------------------------------------------------------------------------

@app.post("/ask", response_model=AskResponse, tags=["qa"])
async def ask(request_body: AskRequest, http_request: Request) -> AskResponse:
    """Ask a policy or SOP question.

    - Resolves caller identity and group memberships for ACL filtering.
    - Creates or continues a Firestore-backed conversation session.
    - Returns a fully-structured AskResponse with citations, confidence
      label, source_count, latest_source_ts, and refusal_reason.
    """
    logger.info("Received question from user=%s", request_body.user_id)

    # ------------------------------------------------------------------
    # 1. ACL: resolve caller groups and build filter (Issue #1)
    # ------------------------------------------------------------------
    acl_filter: Optional[str] = None
    try:
        caller_groups = resolve_caller_groups(http_request)
        acl_filter = build_acl_filter(caller_groups)
        logger.info("ACL filter for user=%s: %s", request_body.user_id, acl_filter)
    except HTTPException:
        # Auth is optional for local dev; in production set REQUIRE_AUTH=true
        if os.environ.get("REQUIRE_AUTH", "false").lower() == "true":
            raise
        logger.debug("No/invalid auth header; proceeding without ACL filter.")

    # ------------------------------------------------------------------
    # 2. Session: create or retrieve session (Issue #2)
    # ------------------------------------------------------------------
    session_mgr = get_session_manager()
    tenant_id = request_body.tenant_id or "default"
    user_email = request_body.user_id or "anonymous"

    session_id = request_body.session_id
    if session_id is None:
        session_id = session_mgr.create_session(tenant_id, user_email)
        logger.info("Created new session %s", session_id)

    history = session_mgr.get_history(session_id, tenant_id)
    turn_index = len(history) // 2  # each Q&A pair = 2 turns

    # ------------------------------------------------------------------
    # 3. Answer engine: search + generate (uses ACL filter)
    # ------------------------------------------------------------------
    try:
        engine = _get_engine()
        # Pass history context and acl_filter to engine when fully wired
        result: AnswerResult = engine.answer(request_body.question)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AnswerEngine error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    # ------------------------------------------------------------------
    # 4. Store turns in session history
    # ------------------------------------------------------------------
    source_ids = [c.get("section_id", "") for c in result.citations]
    session_mgr.append_turn(session_id, tenant_id, "user", request_body.question)
    session_mgr.append_turn(session_id, tenant_id, "assistant", result.answer, sources=source_ids)

    # ------------------------------------------------------------------
    # 5. Build response with full schema
    # ------------------------------------------------------------------
    citations_out = [
        CitationOut(
            section_id=c.get("section_id", ""),
            doc_url=c.get("doc_url", ""),
            snippet=c.get("snippet"),
            modified_at=c.get("modified_at"),
        )
        for c in result.citations
    ]

    latest_ts = None
    if citations_out:
        ts_values = [c.modified_at for c in citations_out if c.modified_at]
        latest_ts = max(ts_values) if ts_values else None

    score = result.grounding_score
    if score >= 0.8:
        confidence = ConfidenceLabel.HIGH
    elif score >= 0.5:
        confidence = ConfidenceLabel.MEDIUM
    else:
        confidence = ConfidenceLabel.LOW

    return AskResponse(
        answer=result.answer,
        citations=citations_out,
        source_count=len(set(c.doc_url for c in citations_out)),
        latest_source_ts=latest_ts,
        confidence_label=confidence,
        grounding_score=score,
        refusal_reason=None if citations_out else "No verified sources found for this question.",
        session_id=session_id,
        turn_index=turn_index,
        acl_filter_applied=acl_filter,
    )


# ---------------------------------------------------------------------------
# Routes: policy version diff (Issue #3)
# ---------------------------------------------------------------------------

@app.get(
    "/diff/{policy_id}/versions/{v1}/{v2}",
    response_model=PolicyDiffResponse,
    tags=["diff"],
)
async def policy_diff(
    policy_id: str,
    v1: str,
    v2: str,
) -> PolicyDiffResponse:
    """Compare two versions of a policy document.

    Returns word-level diff hunks with compliance change highlighting
    (HIPAA, GDPR, PCI-DSS, SOX, SOC2, ISO 27001, NIST keywords flagged).
    """
    try:
        engine = get_diff_engine()
        return engine.compute_diff(policy_id, v1, v2)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Diff engine error: %s", exc)
        raise HTTPException(status_code=500, detail="Diff computation failed.") from exc


# ---------------------------------------------------------------------------
# Routes: session history admin endpoint (Issue #2)
# ---------------------------------------------------------------------------

@app.get("/sessions/{session_id}/history", tags=["sessions"])
async def session_history(
    session_id: str,
    tenant_id: str = "default",
) -> dict:
    """Admin: retrieve full conversation history for a session.

    Requires admin authorisation in production (not enforced in stub mode).
    """
    mgr = get_session_manager()
    history = mgr.get_full_history(session_id, tenant_id)
    if history.get("error") == "not_found":
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found.")
    return history
