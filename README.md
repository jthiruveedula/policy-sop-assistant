# policy-sop-assistant

> GCS-triggered ingestion of wiki/Confluence exports into Vertex AI Search, with Gemini Flash citation-first Q&A that always returns `[source: section_id | doc_url]` references.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![GCP](https://img.shields.io/badge/GCP-Vertex%20AI%20Search%20%7C%20GCS%20%7C%20Eventarc-orange)](https://cloud.google.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Overview

`policy-sop-assistant` is an enterprise knowledge assistant designed for compliance, HR, and operations teams. It ingests policies, SOPs, runbooks, and wiki exports stored in GCS, indexes them in Vertex AI Search (with native grounding), and answers employee questions with **mandatory citations** that include the section ID and a deep link back to the source document.

Key capabilities:
- **Event-driven ingestion**: GCS Object Notifications trigger Eventarc -> Cloud Function -> Vertex AI Search import for any new or updated document.
- **Multi-format parsing**: PDF, DOCX, Markdown, and HTML wiki exports all parsed and section-identified before indexing.
- **Vertex AI Search grounding**: Uses Vertex AI Search's built-in grounding to retrieve relevant passages and generate answers with source metadata.
- **Citation enforcement**: Every answer includes structured citations: `[source: <section_id> | <doc_url>]`. Answers without citations are rejected.
- **Governance-ready**: All source documents are versioned in GCS; audit log via Cloud Audit Logs.

---

## Architecture

```
Confluence / Wiki Export
       |
       v
  GCS Bucket (docs/)
       |  (Object Finalize notification)
       v
  Eventarc -> Cloud Function
       |  (gcs_trigger_handler.py)
       v
  Document Parser
  +--------------------------------+
  | PDF | DOCX | MD | HTML parsers |
  | Section-aware chunker          |
  | Metadata extractor             |
  +--------------------------------+
       |
       v
  Vertex AI Search
  (Data Store + Search App)
       |
       v
  Cloud Run - FastAPI /ask
       |  (search_client.py + citation_formatter.py)
       v
  Gemini 2.0 Flash
  (grounded answer with [source] citations)
       |
       v
  Streamlit UI (citation display)
```

---

## Data Sources & Ingestion

| Source Format | Parser | Section ID Strategy |
|---|---|---|
| PDF | PyMuPDF + pdfplumber | Page number + heading |
| DOCX | python-docx | Heading hierarchy |
| Markdown | mistune | H2/H3 anchors |
| HTML (wiki export) | BeautifulSoup | `id` attributes on headings |

Trigger flow:
1. File uploaded to `gs://my-docs-bucket/docs/`
2. GCS notifies Eventarc
3. Eventarc triggers Cloud Function `ingestion/gcs_trigger_handler.py`
4. Handler parses, extracts sections+metadata, and calls Vertex AI Search import API
5. Document available for search within ~60 seconds

---

## RAG / Search Layer

- **Search engine**: Vertex AI Search (Enterprise edition for grounding).
- **Retrieval mode**: `EXTRACTIVE_ANSWER` + `EXTRACTIVE_SEGMENTS` for passage-level results.
- **Grounding metadata**: Each result includes `document_metadata.uri` (GCS path), `document_metadata.title`, and `page_content` with `page_anchor` (section ID).
- **Citation assembly**: `api/citation_formatter.py` converts Vertex AI Search grounding metadata into structured `[source]` tags.

---

## LLM Usage

| Parameter | Value |
|---|---|
| Model | `gemini-2.0-flash-001` |
| Max input tokens | 4 000 (search results + question) |
| Max output tokens | 1 024 |
| Temperature | 0.1 (compliance-safe, deterministic) |
| Citation requirement | Hard: prompt instructs model to refuse if no source found |
| Grounding source | Vertex AI Search extractive answers |

**Citation format enforced in system prompt:**
```
You MUST cite every factual claim using the format: [source: <section_id> | <doc_url>]
If you cannot find a relevant section, say: "I could not find this in the knowledge base."
Do NOT fabricate citations.
```

---

## Deployment

### Local Dev
```bash
docker-compose up
# Upload a sample doc to trigger ingestion:
python -c "from ingestion.gcs_trigger_handler import process_local_file; process_local_file('sample_docs/sample_policy.pdf')"
# Ask a question:
curl -X POST http://localhost:8080/ask -d '{"question": "What is the remote work policy?"}'
```

### GCP Deployment
```bash
# 1. Provision infra (GCS bucket, Eventarc, Vertex AI Search data store, Cloud Run)
cd infra && terraform apply -var-file=environments/dev.tfvars

# 2. Batch index existing docs
python indexer/build_corpus.py --project=$PROJECT --gcs_bucket=$BUCKET

# 3. Deploy Cloud Function (GCS trigger)
gcloud functions deploy policy-doc-ingestor \
  --gen2 --runtime=python311 \
  --trigger-event-filters="type=google.cloud.storage.object.v1.finalized" \
  --trigger-event-filters="bucket=$BUCKET"

# 4. Deploy API
gcloud run deploy policy-api --source api/ --region=us-central1
```

---

## Repo Structure

```
policy-sop-assistant/
|-- infra/                  # Terraform: GCS, Eventarc, Vertex AI Search, Cloud Run, IAM
|-- ingestion/              # GCS-triggered Cloud Function
|   |-- gcs_trigger_handler.py
|   `-- parsers/            # PDF, DOCX, MD, HTML parsers
|-- indexer/                # Batch corpus builder
|   `-- build_corpus.py
|-- api/                    # FastAPI /ask with citation response
|   |-- main.py
|   |-- search_client.py
|   `-- citation_formatter.py
|-- ui/                     # Streamlit UI with citation display
|-- sample_docs/            # Sample policy/SOP docs for testing
|-- tests/
`-- docs/
```

---

## Roadmap

1. **Access-control integration** - integrate with Google Workspace groups; only return docs the user has GCS read access to.
2. **Multi-language support** - translate non-English docs before indexing; respond in user's language.
3. **Policy diff alerts** - detect when a document changes significantly vs previous version; email affected stakeholders.
