"""ingestion/gcs_trigger_handler.py

Cloud Function (Gen2) triggered by GCS Object Finalize events via Eventarc.
For each new/updated document in the docs bucket:
  1. Download the file from GCS
  2. Parse into sections based on file type
  3. Extract metadata (doc_id, section_ids, title, source_url)
  4. Import into Vertex AI Search data store

Deploy:
  gcloud functions deploy policy-doc-ingestor \\
      --gen2 --runtime=python311 --region=us-central1 \\
      --entry-point=on_gcs_event \\
      --trigger-event-filters=type=google.cloud.storage.object.v1.finalized \\
      --trigger-event-filters=bucket=MY_DOCS_BUCKET \\
      --set-env-vars=PROJECT_ID=my-proj,DATA_STORE_ID=my-data-store
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import tempfile
from pathlib import Path

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import storage

from ingestion.parsers.pdf_parser import PDFParser
from ingestion.parsers.docx_parser import DocxParser
from ingestion.parsers.markdown_parser import MarkdownParser
from ingestion.parsers.html_parser import HTMLParser
from ingestion.metadata_extractor import extract_metadata
from ingestion.chunker import SectionChunker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (from env vars)
# ---------------------------------------------------------------------------

PROJECT_ID = os.environ.get("PROJECT_ID", "")
LOCATION = os.environ.get("LOCATION", "global")
DATA_STORE_ID = os.environ.get("DATA_STORE_ID", "")
COLLECTION = "default_collection"

# Map MIME types to parser classes
PARSER_MAP = {
    "application/pdf": PDFParser,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocxParser,
    "text/markdown": MarkdownParser,
    "text/plain": MarkdownParser,   # treat plain text as markdown
    "text/html": HTMLParser,
}


# ---------------------------------------------------------------------------
# Cloud Function entrypoint
# ---------------------------------------------------------------------------

@functions_framework.cloud_event
def on_gcs_event(cloud_event: CloudEvent) -> None:
    """Handle a GCS Object Finalize event.

    This function is called by Eventarc whenever a file is created or
    updated in the watched GCS bucket.
    """
    data = cloud_event.data
    bucket_name: str = data["bucket"]
    object_name: str = data["name"]
    content_type: str = data.get("contentType", "")

    logger.info("GCS event: gs://%s/%s (type=%s)", bucket_name, object_name, content_type)

    # Skip non-document objects (e.g., folder markers, temp files)
    if object_name.endswith("/") or object_name.startswith("."):
        logger.info("Skipping non-document object: %s", object_name)
        return

    # Infer MIME type from filename if not provided
    if not content_type:
        content_type, _ = mimetypes.guess_type(object_name)
        content_type = content_type or "application/octet-stream"

    if content_type not in PARSER_MAP:
        logger.warning("Unsupported content type '%s' for %s", content_type, object_name)
        return

    process_gcs_object(
        bucket_name=bucket_name,
        object_name=object_name,
        content_type=content_type,
    )


# ---------------------------------------------------------------------------
# Core processing logic
# ---------------------------------------------------------------------------

def process_gcs_object(bucket_name: str, object_name: str,
                       content_type: str) -> None:
    """Download, parse, and import a single GCS object into Vertex AI Search."""
    gcs_uri = f"gs://{bucket_name}/{object_name}"

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / Path(object_name).name

        # 1. Download from GCS
        logger.info("Downloading %s", gcs_uri)
        _download_gcs_file(bucket_name, object_name, str(local_path))

        # 2. Parse into sections
        parser_cls = PARSER_MAP[content_type]
        parser = parser_cls()
        sections = parser.parse(str(local_path))
        logger.info("Parsed %d sections from %s", len(sections), object_name)

        if not sections:
            logger.warning("No sections extracted from %s", object_name)
            return

        # 3. Extract metadata
        metadata = extract_metadata(
            gcs_uri=gcs_uri,
            object_name=object_name,
            sections=sections,
        )

        # 4. Import into Vertex AI Search
        _import_to_vertex_search(metadata, sections)

    logger.info("Successfully processed: %s", gcs_uri)


def process_local_file(local_path: str) -> None:
    """Process a local file (for local development / testing without GCS)."""
    path = Path(local_path)
    content_type, _ = mimetypes.guess_type(str(path))
    content_type = content_type or "application/octet-stream"

    if content_type not in PARSER_MAP:
        raise ValueError(f"Unsupported content type: {content_type}")

    parser_cls = PARSER_MAP[content_type]
    parser = parser_cls()
    sections = parser.parse(str(path))

    logger.info("[LOCAL] Parsed %d sections from %s", len(sections), path.name)
    for i, s in enumerate(sections[:3]):
        logger.info("  Section %d: id=%s text_len=%d", i, s.get("section_id"), len(s.get("text", "")))

    # TODO: call _import_to_vertex_search when running against a real GCP project


# ---------------------------------------------------------------------------
# GCS + Vertex AI Search helpers
# ---------------------------------------------------------------------------

def _download_gcs_file(bucket_name: str, object_name: str,
                       local_path: str) -> None:
    """Download a GCS object to a local path."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.download_to_filename(local_path)
    logger.debug("Downloaded %s -> %s", object_name, local_path)


def _import_to_vertex_search(metadata: dict, sections: list[dict]) -> None:
    """Import document sections into Vertex AI Search data store.

    Uses the discoveryengine v1 client to create/update a document.
    Each section becomes a structured field in the document content.

    TODO: switch to batch import when processing large numbers of documents.
    """
    # TODO: implement using google-cloud-discoveryengine
    # from google.cloud import discoveryengine_v1 as discoveryengine
    # client = discoveryengine.DocumentServiceClient()
    # parent = client.branch_path(PROJECT_ID, LOCATION, DATA_STORE_ID, COLLECTION, "default_branch")
    # document = discoveryengine.Document(
    #     id=metadata["doc_id"],
    #     json_data=json.dumps({
    #         "title": metadata["title"],
    #         "source_url": metadata["source_url"],
    #         "sections": sections,
    #     }),
    # )
    # client.create_document(parent=parent, document=document, document_id=metadata["doc_id"])
    logger.info(
        "[STUB] Would import doc_id=%s with %d sections to Vertex AI Search data store: %s",
        metadata.get("doc_id"), len(sections), DATA_STORE_ID,
    )
