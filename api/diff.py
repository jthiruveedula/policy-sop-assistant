"""api/diff.py

Policy version diff engine for the Policy SOP Assistant.

Implements Issue #3: side-by-side policy version comparison with word-level
diff, compliance change highlighting, and summary statistics.

Endpoint:
    GET /diff/{policy_id}/versions/{v1}/{v2}

Returns a PolicyDiffResponse with diff hunks annotated for compliance
relevance (HIPAA, PCI-DSS, GDPR, SOX, SOC2, ISO 27001, NIST keywords).
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from google.cloud import storage  # type: ignore

from api.models import DiffHunk, PolicyDiffResponse

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("DOCS_BUCKET", "policy-sop-docs")
PROJECT_ID = os.environ.get("PROJECT_ID", "my-gcp-project")

# ---------------------------------------------------------------------------
# Compliance keyword dictionary
# When a changed block contains any of these terms it is flagged as
# compliance-relevant so analysts can review it separately.
# ---------------------------------------------------------------------------
COMPLIANCE_KEYWORDS: List[str] = [
    # Regulatory frameworks
    "HIPAA", "GDPR", "CCPA", "PCI-DSS", "PCI DSS", "SOX", "SOC 2", "SOC2",
    "ISO 27001", "NIST", "FedRAMP", "FISMA", "FERPA",
    # Data handling
    "data retention", "data breach", "personal data", "PII", "PHI",
    "sensitive data", "encryption", "data classification",
    # Access control
    "access control", "least privilege", "MFA", "multi-factor", "password policy",
    "privileged access", "IAM", "RBAC",
    # Incident response
    "incident response", "breach notification", "security incident",
    "disaster recovery", "RTO", "RPO",
    # Compliance obligations
    "audit log", "audit trail", "compliance", "regulatory", "obligation",
    "penalty", "fine", "liability", "right to erasure", "data subject",
]


class PolicyDiffEngine:
    """Computes word-level diffs between two policy document versions.

    Fetches document text from GCS (or a stub) and applies diff-match-patch
    to produce annotated diff hunks.
    """

    def __init__(self) -> None:
        self._gcs = self._build_gcs_client()
        self._dmp = self._build_dmp()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_diff(
        self,
        policy_id: str,
        version_old: str,
        version_new: str,
    ) -> PolicyDiffResponse:
        """Fetch both policy versions and return an annotated diff.

        Args:
            policy_id: Logical policy identifier (e.g. "hr-policy-001").
            version_old: Old version label (e.g. "v1", "2025-01").
            version_new: New version label (e.g. "v2", "2025-07").

        Returns:
            PolicyDiffResponse with hunks, statistics, and compliance flags.
        """
        text_old = self._fetch_version(policy_id, version_old)
        text_new = self._fetch_version(policy_id, version_new)

        hunks = self._diff(text_old, text_new)

        additions = sum(1 for h in hunks if h.op == "insert")
        deletions = sum(1 for h in hunks if h.op == "delete")
        compliance_changes = sum(1 for h in hunks if h.is_compliance_relevant)

        summary = self._build_summary(additions, deletions, compliance_changes)

        return PolicyDiffResponse(
            policy_id=policy_id,
            version_old=version_old,
            version_new=version_new,
            hunks=hunks,
            additions=additions,
            deletions=deletions,
            compliance_changes=compliance_changes,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_version(self, policy_id: str, version: str) -> str:
        """Fetch document text from GCS.

        GCS path convention: gs://{DOCS_BUCKET}/versions/{policy_id}/{version}.txt
        Falls back to a stub if GCS is not available.
        """
        if self._gcs is None:
            return self._stub_text(policy_id, version)

        blob_path = f"versions/{policy_id}/{version}.txt"
        try:
            bucket = self._gcs.bucket(GCS_BUCKET)
            blob = bucket.blob(blob_path)
            text = blob.download_as_text(encoding="utf-8")
            logger.info("Fetched gs://%s/%s (%d chars)", GCS_BUCKET, blob_path, len(text))
            return text
        except Exception as exc:  # noqa: BLE001
            logger.warning("GCS fetch failed for %s/%s: %s", policy_id, version, exc)
            return self._stub_text(policy_id, version)

    def _diff(self, text_old: str, text_new: str) -> List[DiffHunk]:
        """Compute word-level diff and return annotated hunks."""
        if self._dmp is None:
            # Fallback: simple line-level diff without diff-match-patch
            return self._naive_diff(text_old, text_new)

        # Use diff-match-patch with semantic cleanup for word-level granularity
        diffs = self._dmp.diff_main(text_old, text_new)
        self._dmp.diff_cleanupSemantic(diffs)

        hunks: List[DiffHunk] = []
        op_map = {-1: "delete", 0: "equal", 1: "insert"}

        for op_code, text in diffs:
            op = op_map[op_code]
            keywords = self._compliance_keywords_in(text) if op != "equal" else []
            hunks.append(
                DiffHunk(
                    op=op,
                    text=text,
                    is_compliance_relevant=bool(keywords),
                    compliance_keywords=keywords,
                )
            )

        return hunks

    def _naive_diff(self, text_old: str, text_new: str) -> List[DiffHunk]:
        """Simple line-level diff as fallback when diff-match-patch is unavailable."""
        import difflib
        hunks: List[DiffHunk] = []
        matcher = difflib.SequenceMatcher(None, text_old.splitlines(), text_new.splitlines())
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                text = "\n".join(text_old.splitlines()[i1:i2])
                hunks.append(DiffHunk(op="equal", text=text))
            elif tag in ("replace", "delete"):
                text = "\n".join(text_old.splitlines()[i1:i2])
                kw = self._compliance_keywords_in(text)
                hunks.append(DiffHunk(op="delete", text=text, is_compliance_relevant=bool(kw), compliance_keywords=kw))
            if tag in ("replace", "insert"):
                text = "\n".join(text_new.splitlines()[j1:j2])
                kw = self._compliance_keywords_in(text)
                hunks.append(DiffHunk(op="insert", text=text, is_compliance_relevant=bool(kw), compliance_keywords=kw))
        return hunks

    @staticmethod
    def _compliance_keywords_in(text: str) -> List[str]:
        """Return list of compliance keywords found in *text* (case-insensitive)."""
        found: List[str] = []
        text_lower = text.lower()
        for kw in COMPLIANCE_KEYWORDS:
            if kw.lower() in text_lower:
                found.append(kw)
        return found

    @staticmethod
    def _build_summary(additions: int, deletions: int, compliance: int) -> str:
        parts = []
        if additions:
            parts.append(f"{additions} addition{'s' if additions != 1 else ''}")
        if deletions:
            parts.append(f"{deletions} deletion{'s' if deletions != 1 else ''}")
        if compliance:
            parts.append(f"{compliance} compliance-related change{'s' if compliance != 1 else ''}")
        if not parts:
            return "No differences found."
        return ", ".join(parts) + "."

    def _build_gcs_client(self) -> Any:
        try:
            client = storage.Client(project=PROJECT_ID)
            logger.info("GCS client initialised for diff engine.")
            return client
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not init GCS client for diff: %s", exc)
            return None

    def _build_dmp(self) -> Any:
        try:
            import diff_match_patch as dmp_module  # type: ignore
            dmp = dmp_module.diff_match_patch()
            logger.info("diff-match-patch loaded.")
            return dmp
        except ImportError:
            logger.warning("diff-match-patch not installed; falling back to difflib.")
            return None

    @staticmethod
    def _stub_text(policy_id: str, version: str) -> str:
        return (
            f"[STUB] Policy document for {policy_id} version {version}.\n"
            "Section 1: Data Retention Policy\n"
            "All customer data must be retained for 7 years in compliance with GDPR and HIPAA.\n"
            "Access control is enforced via IAM roles. Encryption is required at rest and in transit.\n"
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine: Optional[PolicyDiffEngine] = None


def get_diff_engine() -> PolicyDiffEngine:
    """Return the module-level PolicyDiffEngine singleton."""
    global _engine
    if _engine is None:
        _engine = PolicyDiffEngine()
    return _engine
