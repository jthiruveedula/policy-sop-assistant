"""ingestion/metadata_extractor.py

Extracts standard metadata from a GCS object path + parsed sections.
Returns a dict consumed by the Vertex AI Search importer.
"""
from __future__ import annotations

import hashlib
import os
import re
from typing import Any, Dict, List


def extract_metadata(
    bucket_name: str,
    object_name: str,
    sections: List[Any],
) -> Dict[str, Any]:
    """Build metadata dict for a GCS object.

    Args:
        bucket_name: GCS bucket name.
        object_name: GCS object path (e.g. "policies/hr/leave-policy.pdf").
        sections: Parsed section objects (must have .section_id / .title attrs).

    Returns:
        A dict with keys: doc_id, title, source_url, section_count,
        section_ids, bucket, object_path.
    """
    # Derive a stable doc_id from object path
    doc_id = hashlib.md5(object_name.encode()).hexdigest()[:16]

    # Human-readable title from filename (without extension)
    filename = os.path.basename(object_name)
    title = _titleize(os.path.splitext(filename)[0])

    source_url = f"https://storage.googleapis.com/{bucket_name}/{object_name}"

    section_ids = [getattr(s, "section_id", str(i)) for i, s in enumerate(sections)]

    return {
        "doc_id": doc_id,
        "title": title,
        "source_url": source_url,
        "section_count": len(sections),
        "section_ids": section_ids,
        "bucket": bucket_name,
        "object_path": object_name,
    }


def _titleize(slug: str) -> str:
    """Convert a filename slug to a human-readable title."""
    return re.sub(r"[-_]+", " ", slug).title()

