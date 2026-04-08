# 🛡️ Policy / SOP Assistant

> A governed enterprise policy copilot that ingests SOPs, runbooks, and wiki exports, then returns grounded answers with mandatory source citations and operational traceability.

[![Build](https://img.shields.io/badge/build-passing-brightgreen)](https://github.com/jthiruveedula/policy-sop-assistant/actions)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![GCP](https://img.shields.io/badge/GCP-Cloud%20Run%20%7C%20Eventarc%20%7C%20GCS-4285F4)](https://cloud.google.com/)
[![Vertex AI Search](https://img.shields.io/badge/search-Vertex%20AI%20Search-1A73E8)](https://cloud.google.com/vertex-ai-search)
[![Gemini](https://img.shields.io/badge/model-Gemini%202.0%20Flash-8E75FF)](https://cloud.google.com/vertex-ai)
[![Citations](https://img.shields.io/badge/citations-enforced-orange)](https://github.com/jthiruveedula/policy-sop-assistant)
[![Governance](https://img.shields.io/badge/governance-ready-green)](https://github.com/jthiruveedula/policy-sop-assistant)
[![License](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

---

## 🛡️ Why Trust This Assistant

Policy and SOP information is high-stakes. A wrong answer can cause compliance failures, operational incidents, or legal risk.  
`policy-sop-assistant` is built trust-first: every answer **must** include `[source: <section_id> | <doc_url>]` citations or it is rejected. Documents are GCS-versioned, ingestion is event-driven, and all queries are audit-logged via Cloud Audit Logs.

---

## 🏗️ Architecture

```
Confluence / Wiki Export
       |
       v
  GCS Bucket (docs/)
       |  (Object Finalize notification)
       v
  Eventarc -> Cloud Function
       |  (parse + section-chunk + metadata tag)
       v
  Vertex AI Search  (native grounding + citation passthrough)
       |
       v
  Cloud Run  -  FastAPI /ask
       |           |
  Streamlit UI   Gemini 2.0 Flash
  (citation panel)   (citation-enforced generation)
```

---

## 🔌 API Contract

Every `/ask` response returns this structured schema:

```json
{
  "answer": "string",
  "citations": [
    {
      "section_id": "string",
      "doc_url": "string",
      "snippet": "string",
      "modified_at": "ISO8601"
    }
  ],
  "source_count": 3,
  "latest_source_ts": "ISO8601",
  "confidence_label": "high | medium | low",
  "refusal_reason": null
}
```

Answers without at least one valid citation are **rejected at the QA layer** (`qa/citation_enforcer.py`).

---

## 📥 Ingestion Flow

| Step | Component | Detail |
|---|---|---|
| 1. Upload | GCS bucket (`docs/`) | Confluence export, PDF, DOCX, Markdown |
| 2. Trigger | Eventarc Object Finalize | Auto-fires on new/updated file |
| 3. Parse | `ingestion/parser.py` | Multi-format, section-aware chunking |
| 4. Index | Vertex AI Search import | Native grounding with source metadata |
| 5. Diff | `ingestion/diff_detector.py` | 🆕 Section-level change detection on update |

---

## 📁 Repo Structure

```
policy-sop-assistant/
├── api/                    # FastAPI /ask service (Cloud Run)
│   ├── main.py
│   ├── models.py           # 🆕 Structured response schema (citations, confidence)
│   ├── search_client.py
│   └── authz.py            # 🆕 Access-aware retrieval (IAM / ACL filter)
├── ingestion/              # GCS-triggered document ingestion
│   ├── parser.py
│   ├── section_chunker.py
│   ├── diff_detector.py    # 🆕 Section-level policy diff on update
│   └── telemetry.py        # 🆕 Parse success rate, chunk counts, error categories
├── qa/                     # Citation enforcement & evaluation
│   ├── citation_enforcer.py
│   ├── eval_runner.py      # 🆕 Groundedness + citation validity scoring
│   └── golden_questions.yaml  # 🆕 Curated eval question set
├── terraform/              # GCS, Eventarc, Cloud Run, IAM, Vertex AI Search
├── ui/                     # Streamlit chat UI with citation panel
├── cloudbuild.yaml
└── requirements.txt
```

---

## 🚀 Quickstart

```bash
# Local dev
pip install -r requirements.txt
export PROJECT_ID=your-project
uvicorn api.main:app --reload

# GCP deploy
cd terraform && terraform init && terraform apply
gcloud run deploy policy-sop-api --source api/ --region=us-central1

# Run evaluation suite
python qa/eval_runner.py --questions qa/golden_questions.yaml
```

---

## 💬 Example Policy Questions

```
"What is the process for requesting access to a production database?"
"What are our data retention obligations for EU customer records?"
"Who approves exceptions to the change management SOP?"
"Has the incident response policy changed in the last 30 days?"
```

---

## 📊 LLM Usage

| Parameter | Value |
|---|---|
| Model | `gemini-2.0-flash-001` |
| Grounding | Vertex AI Search (native) |
| Citation format | `[source: <section_id> \| <doc_url>]` |
| Refusal | Answer rejected if 0 valid citations |
| Audit log | Cloud Audit Logs (all queries) |

---

## 🔭 Operations / Observability

- **Ingestion telemetry**: `ingestion/telemetry.py` — parse success rate, skipped sections, error categories
- **Evaluation harness**: `qa/eval_runner.py` — citation validity, groundedness, refusal correctness
- **Admin dashboard**: `/admin/ingestion-status` endpoint (planned) — pipeline health at a glance
- **Policy diff alerts**: `ingestion/diff_detector.py` — section-level change summary on every document update

---

## 🛣️ Roadmap

### Now / Next
- [ ] **Access-Aware Retrieval** — IAM / ACL-based document visibility filter at query time
- [ ] **Policy Diff Pipeline** — section-level diff + change summary on every document update
- [ ] **Evaluation Suite** — golden questions for groundedness, citation validity, refusal correctness
- [ ] **Ingestion Observability** — parse failure console + admin API endpoint
- [ ] **Structured Response Schema** — citations, confidence label, refusal reason in every response

### Future / Wow
- [ ] **Procedure Navigator** — step-by-step SOP flows with branching logic and completion tracking
- [ ] **Policy Impact Agent** — on policy change, identify affected teams, SOPs, and training needs
- [ ] **Multilingual Grounded Answers** — ingest once, answer in user's language with source traceability
- [ ] **Exception Triage Agent** — route ambiguous questions to human owners with cited context
- [ ] **Compliance Analytics Layer** — unanswered questions, confusing sections, top policy pain points

---

## 🤝 Contributing

PRs welcome. Run `make lint test` before opening a PR.

## 📄 License

MIT — see [LICENSE](LICENSE)
