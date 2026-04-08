"""api/main.py

Cloud Run FastAPI service for the Policy SOP Assistant.
Exposes a single POST /ask endpoint that delegates to the AnswerEngine.

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

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from qa.answer_engine import AnswerEngine, AnswerResult

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Policy SOP Assistant",
    description="Enterprise Q&A with mandatory Vertex AI Search citations.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ALLOWED_ORIGIN", "*")],
    allow_methods=["POST", "GET"],
    allow_headers=["*"],
)

_engine: Optional[AnswerEngine] = None


def _get_engine() -> AnswerEngine:
    global _engine
    if _engine is None:
        _engine = AnswerEngine()
    return _engine


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    user_id: Optional[str] = None


class CitationOut(BaseModel):
    section_id: str
    doc_url: str


class AskResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    grounding_score: float


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health() -> dict:
    """Health check for Cloud Run liveness probe."""
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """Ask a policy or SOP question.

    Returns a cited answer sourced from the Vertex AI Search data store.
    """
    logger.info("Received question from user=%s", request.user_id)

    try:
        result: AnswerResult = _get_engine().answer(request.question)
    except Exception as exc:  # noqa: BLE001
        logger.exception("AnswerEngine error: %s", exc)
        raise HTTPException(status_code=500, detail="Internal server error") from exc

    citations_out = [
        CitationOut(section_id=c["section_id"], doc_url=c["doc_url"])
        for c in result.citations
    ]

    return AskResponse(
        answer=result.answer,
        citations=citations_out,
        grounding_score=result.grounding_score,
    )

