"""api/session.py

Firestore-backed conversation session manager for the Policy SOP Assistant.

Implements Issue #2: multi-turn conversation memory with session context
and Firestore state persistence.

Firestore document layout:
  sessions/{tenant_id}/{session_id}  (metadata)
  sessions/{tenant_id}/{session_id}/turns/{turn_index}  (individual turns)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

FIRESTORE_PROJECT = os.environ.get("PROJECT_ID", "my-gcp-project")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "24"))
MAX_TURNS_DEFAULT = int(os.environ.get("SESSION_MAX_TURNS", "20"))
HISTORY_WINDOW = int(os.environ.get("SESSION_HISTORY_WINDOW", "5"))


class SessionManager:
    """Manages conversation sessions backed by Cloud Firestore.

    Implements per-tenant isolation: sessions are stored under
    ``sessions/{tenant_id}/{session_id}`` so security rules can enforce
    tenant boundaries.
    """

    def __init__(self) -> None:
        self._db = self._build_client()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_session(self, tenant_id: str, user_email: str) -> str:
        """Create a new session document and return the session_id.

        Args:
            tenant_id: Tenant scope extracted from the verified JWT.
            user_email: Caller email for audit purposes.

        Returns:
            A new UUID session_id string.
        """
        session_id = str(uuid.uuid4())
        now = self._utcnow()
        expires_at = now + timedelta(hours=SESSION_TTL_HOURS)

        doc_data = {
            "session_id": session_id,
            "tenant_id": tenant_id,
            "user_email": user_email,
            "created_at": now.isoformat(),
            "last_active_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),  # Firestore TTL field
            "turn_count": 0,
        }

        if self._db is not None:
            try:
                ref = self._db.collection("sessions").document(tenant_id).collection("sessions").document(session_id)
                ref.set(doc_data)
                logger.info("Created session %s for tenant=%s user=%s", session_id, tenant_id, user_email)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Firestore create_session failed: %s", exc)
        else:
            logger.info("[STUB] create_session: session_id=%s", session_id)

        return session_id

    def get_history(
        self,
        session_id: str,
        tenant_id: str,
        max_turns: int = HISTORY_WINDOW,
    ) -> List[Dict[str, Any]]:
        """Retrieve the last *max_turns* conversation turns.

        Returns:
            List of dicts: [{"role": "user"|"assistant", "content": str,
                             "sources": List[str], "created_at": str}]
        """
        if self._db is None:
            logger.info("[STUB] get_history: session_id=%s", session_id)
            return []

        try:
            turns_ref = (
                self._db.collection("sessions")
                .document(tenant_id)
                .collection("sessions")
                .document(session_id)
                .collection("turns")
                .order_by("turn_index", direction="DESCENDING")
                .limit(max_turns)
            )
            docs = turns_ref.get()
            turns = [doc.to_dict() for doc in docs]
            # Re-sort ascending so oldest turn comes first in prompt
            turns.sort(key=lambda t: t.get("turn_index", 0))
            return turns
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firestore get_history failed: %s", exc)
            return []

    def append_turn(
        self,
        session_id: str,
        tenant_id: str,
        role: str,
        content: str,
        sources: Optional[List[str]] = None,
    ) -> int:
        """Append a turn to the session and return the new turn_index.

        Also updates the session's last_active_at and prunes turns that
        exceed MAX_TURNS_DEFAULT to keep token overhead bounded.

        Args:
            session_id: Session UUID.
            tenant_id: Tenant scope.
            role: "user" or "assistant".
            content: The message text.
            sources: List of source section IDs cited in this turn.

        Returns:
            Zero-based turn_index of the newly appended turn.
        """
        if self._db is None:
            logger.info("[STUB] append_turn: session_id=%s role=%s", session_id, role)
            return 0

        try:
            session_ref = (
                self._db.collection("sessions")
                .document(tenant_id)
                .collection("sessions")
                .document(session_id)
            )

            # Transactionally increment turn_count
            session_doc = session_ref.get()
            if not session_doc.exists:
                logger.warning("Session %s not found; auto-creating.", session_id)
                self.create_session(tenant_id, "unknown")
                session_doc = session_ref.get()

            turn_count: int = session_doc.to_dict().get("turn_count", 0)
            turn_index = turn_count  # zero-based

            turn_data = {
                "turn_index": turn_index,
                "role": role,
                "content": content,
                "sources": sources or [],
                "created_at": self._utcnow().isoformat(),
            }

            turns_ref = session_ref.collection("turns").document(str(turn_index))
            turns_ref.set(turn_data)

            # Update session metadata
            now_str = self._utcnow().isoformat()
            expires_str = (self._utcnow() + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
            session_ref.update({
                "turn_count": turn_count + 1,
                "last_active_at": now_str,
                "expires_at": expires_str,  # Rolling TTL refresh
            })

            # Prune oldest turns if we exceed MAX_TURNS_DEFAULT
            if turn_count + 1 > MAX_TURNS_DEFAULT:
                oldest_index = turn_count + 1 - MAX_TURNS_DEFAULT
                for i in range(oldest_index):
                    session_ref.collection("turns").document(str(i)).delete()
                logger.debug("Pruned turns 0..%d for session %s", oldest_index - 1, session_id)

            return turn_index

        except Exception as exc:  # noqa: BLE001
            logger.warning("Firestore append_turn failed: %s", exc)
            return 0

    def expire_session(self, session_id: str, tenant_id: str) -> None:
        """Mark session as expired (sets expires_at to now).

        Cloud Firestore TTL policy will garbage-collect the document
        within 24 hours of the expires_at field being in the past.
        """
        if self._db is None:
            logger.info("[STUB] expire_session: %s", session_id)
            return

        try:
            ref = (
                self._db.collection("sessions")
                .document(tenant_id)
                .collection("sessions")
                .document(session_id)
            )
            ref.update({"expires_at": self._utcnow().isoformat()})
            logger.info("Expired session %s", session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firestore expire_session failed: %s", exc)

    def get_full_history(self, session_id: str, tenant_id: str) -> Dict[str, Any]:
        """Admin endpoint: return the full session metadata + all turns.

        Used by GET /sessions/{session_id}/history (admin-only).
        """
        if self._db is None:
            return {"session_id": session_id, "turns": [], "stub": True}

        try:
            session_ref = (
                self._db.collection("sessions")
                .document(tenant_id)
                .collection("sessions")
                .document(session_id)
            )
            session_doc = session_ref.get()
            if not session_doc.exists:
                return {"session_id": session_id, "turns": [], "error": "not_found"}

            metadata = session_doc.to_dict()
            turns_docs = session_ref.collection("turns").order_by("turn_index").get()
            metadata["turns"] = [t.to_dict() for t in turns_docs]
            return metadata
        except Exception as exc:  # noqa: BLE001
            logger.warning("Firestore get_full_history failed: %s", exc)
            return {"session_id": session_id, "turns": [], "error": str(exc)}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> Any:
        """Instantiate the Firestore client."""
        try:
            from google.cloud import firestore  # type: ignore
            db = firestore.Client(project=FIRESTORE_PROJECT)
            logger.info("Firestore client initialised for project=%s", FIRESTORE_PROJECT)
            return db
        except ImportError:
            logger.warning("google-cloud-firestore not installed; sessions run in stub mode.")
            return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not init Firestore client: %s", exc)
            return None

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """Return the module-level SessionManager singleton."""
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager
