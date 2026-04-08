# terraform/main.tf
# Infrastructure-as-Code for policy-sop-assistant
# Provisions: GCS bucket, Vertex AI Search data store, Cloud Run service,
# Cloud Function, Eventarc trigger, and IAM bindings.

terraform {
  required_version = ">= 1.5"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }

  backend "gcs" {
    # Configure before use:
    # bucket = "<your-tf-state-bucket>"
    # prefix = "policy-sop-assistant/state"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------
variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "docs_bucket_name" {
  description = "GCS bucket for policy documents"
  type        = string
  default     = "policy-docs-raw"
}

variable "data_store_id" {
  description = "Vertex AI Search data store ID"
  type        = string
  default     = "policy-docs"
}

# ---------------------------------------------------------------------------
# GCS bucket for policy documents
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "docs" {
  name                        = "${var.project_id}-${var.docs_bucket_name}"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning { enabled = true }

  lifecycle_rule {
    condition { age = 365 }
    action { type = "SetStorageClass"; storage_class = "NEARLINE" }
  }
}

# ---------------------------------------------------------------------------
# Vertex AI Search data store
# ---------------------------------------------------------------------------
resource "google_discovery_engine_data_store" "policy_docs" {
  location                    = var.region
  data_store_id               = var.data_store_id
  display_name                = "Policy SOP Documents"
  industry_vertical           = "GENERIC"
  content_config              = "CONTENT_REQUIRED"
  solution_types              = ["SOLUTION_TYPE_SEARCH"]
  create_advanced_site_search = false
}

# ---------------------------------------------------------------------------
# Service account for Cloud Function
# ---------------------------------------------------------------------------
resource "google_service_account" "ingestor" {
  account_id   = "policy-doc-ingestor-sa"
  display_name = "Policy Doc Ingestor SA"
}

resource "google_project_iam_member" "ingestor_storage" {
  project = var.project_id
  role    = "roles/storage.objectViewer"
  member  = "serviceAccount:${google_service_account.ingestor.email}"
}

resource "google_project_iam_member" "ingestor_discoveryengine" {
  project = var.project_id
  role    = "roles/discoveryengine.editor"
  member  = "serviceAccount:${google_service_account.ingestor.email}"
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------
output "docs_bucket" {
  description = "GCS bucket for policy documents"
  value       = google_storage_bucket.docs.name
}

output "data_store_id" {
  description = "Vertex AI Search data store ID"
  value       = google_discovery_engine_data_store.policy_docs.data_store_id
}

output "ingestor_sa_email" {
  description = "Service account email for the ingestion Cloud Function"
  value       = google_service_account.ingestor.email
}

