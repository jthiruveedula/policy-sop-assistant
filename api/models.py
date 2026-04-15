"""api/models.py

Pydantic request/response models for the Policy SOP Assistant API.

Provides the full structured schema described in the README API contract:
  answer, citations[], source_count, latest_source_ts,
  confidence_label, refusal_reason, session_id, turn_index.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ConfidenceLabel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ---------------------------------------------------------------------------
# Citation schema
# ---------------------------------------------------------------------------

class CitationOut(BaseModel):
    """A single source citation returned by the answer engine."""

    section_id: str = Field(..., description="Unique section identifier within the source document.")
    doc_url: str = Field(..., description="Canonical URL of the source document.")
    snippet: Optional[str] = Field(
        default=None,
        description="Short extract from the source section that supports the answer.",
    )
    modified_at: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of last document modification.",
    )


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    """POST /ask request body."""

    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The policy or SOP question to answer.",
    )
    user_id: Optional[str] = Field(
        default=None,
        description="Optional caller identifier; used for audit logging.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Conversation session UUID. Supply to continue a prior session.",
    )
    tenant_id: Optional[str] = Field(
        default=None,
        description="Tenant scope for multi-tenant deployments.",
    )

    model_config = {"json_schema_extra": {
        "examples": [
            {
                "question": "What is the data retention policy for EU customer records?",
                "user_id": "user@example.com",
            }
        ]
    }}


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class AskResponse(BaseModel):
    """POST /ask response body — full API contract."""

    answer: str = Field(
        ...,
        description="Grounded answer text containing inline citation markers.",
    )
    citations: List[CitationOut] = Field(
        default_factory=list,
        description="List of source citations that ground the answer.",
    )
    source_count: int = Field(
        default=0,
        ge=0,
        description="Number of distinct source documents cited.",
    )
    latest_source_ts: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of the most recently modified cited source.",
    )
    confidence_label: ConfidenceLabel = Field(
        default=ConfidenceLabel.LOW,
        description="Confidence tier derived from grounding score.",
    )
    grounding_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Normalised grounding score in [0, 1].",
    )
    refusal_reason: Optional[str] = Field(
        default=None,
        description="Non-null when the answer was refused due to missing citations.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session UUID; echo back to client for follow-up questions.",
    )
    turn_index: Optional[int] = Field(
        default=None,
        ge=0,
        description="Zero-based turn index within the session.",
    )
    acl_filter_applied: Optional[str] = Field(
        default=None,
        description="Vertex AI Search filter expression used (for audit). Logged but not displayed in UI.",
    )

    @classmethod
    def from_grounding_score(cls, score: float, **kwargs) -> "AskResponse":
        """Convenience constructor that auto-derives confidence_label from grounding_score."""
        if score >= 0.8:
            label = ConfidenceLabel.HIGH
        elif score >= 0.5:
            label = ConfidenceLabel.MEDIUM
        else:
            label = ConfidenceLabel.LOW
        return cls(grounding_score=score, confidence_label=label, **kwargs)


# ---------------------------------------------------------------------------
# Session history models (Issue #2)
# ---------------------------------------------------------------------------

class TurnRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class SessionTurn(BaseModel):
    """A single turn in a conversation session."""

    role: TurnRole
    content: str
    sources: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None


class SessionHistoryResponse(BaseModel):
    """GET /sessions/{session_id}/history response."""

    session_id: str
    tenant_id: str
    user_email: str
    turns: List[SessionTurn]
    created_at: Optional[str] = None
    last_active_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Diff models (Issue #3)
# ---------------------------------------------------------------------------

class DiffHunk(BaseModel):
    """A single changed block in a policy version diff."""

    op: Literal["insert", "delete", "equal"]
    text: str
    is_compliance_relevant: bool = False
    compliance_keywords: List[str] = Field(default_factory=list)


class PolicyDiffResponse(BaseModel):
    """GET /diff/{policy_id}/versions/{v1}/{v2} response."""

    policy_id: str
    version_old: str
    version_new: str
    hunks: List[DiffHunk]
    additions: int = 0
    deletions: int = 0
    compliance_changes: int = 0
    summary: str = ""
