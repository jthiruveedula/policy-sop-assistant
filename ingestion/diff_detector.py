"""
diff_detector.py - Section-level policy diff for policy-sop-assistant.

On every document update triggered by GCS, this module compares the
newly parsed sections against the previously indexed version and emits
a structured change summary. The summary is stored in GCS as a sidecar
json file and can be surfaced via the /diff API endpoint.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import storage

logger = logging.getLogger(__name__)

DIFF_STORE_PREFIX = "diffs/"  # GCS prefix for sidecar diff files


@dataclass
class SectionChange:
    section_id: str
    change_type: str  # "added" | "modified" | "removed"
    old_hash: Optional[str]
    new_hash: Optional[str]
    summary: str


@dataclass
class DocumentDiff:
    doc_id: str
    doc_url: str
    detected_at: str  # ISO8601
    changes: List[SectionChange]

    def has_changes(self) -> bool:
        return len(self.changes) > 0


def compute_section_hashes(sections: Dict[str, str]) -> Dict[str, str]:
    """
    Compute a SHA-256 fingerprint for each section's text content.

    Args:
        sections: {section_id: section_text}

    Returns:
        {section_id: sha256_hex}
    """
    return {
        sid: hashlib.sha256(text.encode()).hexdigest()
        for sid, text in sections.items()
    }


def detect_diff(
    doc_id: str,
    doc_url: str,
    new_sections: Dict[str, str],
    old_sections: Optional[Dict[str, str]] = None,
) -> DocumentDiff:
    """
    Compare new sections against old sections and return a DocumentDiff.

    Args:
        doc_id:       Unique document identifier.
        doc_url:      GCS or Confluence URL of the document.
        new_sections: Freshly parsed sections {section_id: text}.
        old_sections: Previously indexed sections {section_id: text}.
                      None means the document is brand-new.

    Returns:
        DocumentDiff with a list of SectionChange entries.
    """
    if old_sections is None:
        old_sections = {}

    new_hashes = compute_section_hashes(new_sections)
    old_hashes = compute_section_hashes(old_sections)

    changes: List[SectionChange] = []

    # Detect added and modified sections
    for sid, new_hash in new_hashes.items():
        old_hash = old_hashes.get(sid)
        if old_hash is None:
            changes.append(SectionChange(
                section_id=sid,
                change_type="added",
                old_hash=None,
                new_hash=new_hash,
                summary=f"Section '{sid}' was added.",
            ))
        elif old_hash != new_hash:
            changes.append(SectionChange(
                section_id=sid,
                change_type="modified",
                old_hash=old_hash,
                new_hash=new_hash,
                summary=f"Section '{sid}' was modified.",
            ))

    # Detect removed sections
    for sid in old_hashes:
        if sid not in new_hashes:
            changes.append(SectionChange(
                section_id=sid,
                change_type="removed",
                old_hash=old_hashes[sid],
                new_hash=None,
                summary=f"Section '{sid}' was removed.",
            ))

    diff = DocumentDiff(
        doc_id=doc_id,
        doc_url=doc_url,
        detected_at=datetime.now(timezone.utc).isoformat(),
        changes=changes,
    )
    logger.info(
        "Diff for doc %s: %d change(s) detected.", doc_id, len(changes)
    )
    return diff


def store_diff(bucket_name: str, diff: DocumentDiff) -> str:
    """
    Persist the DocumentDiff as a JSON sidecar file in GCS.

    Returns the GCS object path.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    object_path = f"{DIFF_STORE_PREFIX}{diff.doc_id}/latest.json"
    blob = bucket.blob(object_path)
    blob.upload_from_string(
        json.dumps(asdict(diff), indent=2),
        content_type="application/json",
    )
    logger.info("Diff stored at gs://%s/%s", bucket_name, object_path)
    return object_path


def load_previous_sections(
    bucket_name: str, doc_id: str
) -> Optional[Dict[str, str]]:
    """
    Load previously indexed sections from GCS sidecar store.
    Returns None if no previous version exists.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    object_path = f"{DIFF_STORE_PREFIX}{doc_id}/sections.json"
    blob = bucket.blob(object_path)
    if not blob.exists():
        return None
    return json.loads(blob.download_as_text())


def store_sections(
    bucket_name: str, doc_id: str, sections: Dict[str, str]
) -> None:
    """Persist current sections as the new baseline for future diffs."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    object_path = f"{DIFF_STORE_PREFIX}{doc_id}/sections.json"
    bucket.blob(object_path).upload_from_string(
        json.dumps(sections, indent=2),
        content_type="application/json",
    )
