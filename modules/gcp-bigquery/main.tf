variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }

variable "writer_members" {
  type    = list(string)
  default = []
}

variable "reader_members" {
  type        = list(string)
  description = "Dashboard readers (e.g. group:pmo@example.com). Grant per-tenant access with authorized views, not here."
  default     = []
}

variable "kms_key_id" {
  type    = string
  default = null
}

variable "delete_contents_on_destroy" {
  type    = bool
  default = false
}

locals {
  schemas = {
    agent_runs = [
      { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
      { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
      { name = "project_id", type = "STRING", mode = "REQUIRED" },
      { name = "agent_id", type = "STRING", mode = "REQUIRED" },
      { name = "event_type", type = "STRING", mode = "NULLABLE" },
      { name = "status", type = "STRING", mode = "NULLABLE" },
      { name = "proposals", type = "INTEGER", mode = "NULLABLE" },
      { name = "dropped", type = "INTEGER", mode = "NULLABLE" },
      { name = "duration_s", type = "FLOAT", mode = "NULLABLE" },
      { name = "input_tokens", type = "INTEGER", mode = "NULLABLE" },
      { name = "output_tokens", type = "INTEGER", mode = "NULLABLE" },
    ]
    hitl_decisions = [
      { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
      { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
      { name = "project_id", type = "STRING", mode = "REQUIRED" },
      { name = "checkpoint", type = "STRING", mode = "NULLABLE" },
      { name = "kind", type = "STRING", mode = "NULLABLE" },
      { name = "agent_id", type = "STRING", mode = "NULLABLE" },
      { name = "tier", type = "INTEGER", mode = "NULLABLE" },
      { name = "outcome", type = "STRING", mode = "NULLABLE" },
      { name = "role", type = "STRING", mode = "NULLABLE" },
      { name = "latency_hours", type = "FLOAT", mode = "NULLABLE" },
      { name = "escalation_level", type = "INTEGER", mode = "NULLABLE" },
    ]
    quality_scores = [
      { name = "ts", type = "TIMESTAMP", mode = "REQUIRED" },
      { name = "tenant_id", type = "STRING", mode = "REQUIRED" },
      { name = "project_id", type = "STRING", mode = "REQUIRED" },
      { name = "subject_type", type = "STRING", mode = "NULLABLE" },
      { name = "subject_id", type = "STRING", mode = "NULLABLE" },
      { name = "total", type = "FLOAT", mode = "NULLABLE" },
      { name = "rating", type = "STRING", mode = "NULLABLE" },
      { name = "rubric_version", type = "STRING", mode = "NULLABLE" },
    ]
  }
}

resource "google_bigquery_dataset" "analytics" {
  dataset_id                 = "auranexus_${var.environment}"
  project                    = var.project_id
  location                   = var.region
  description                = "PM dashboards, HITL latency and quality scoring"
  delete_contents_on_destroy = var.delete_contents_on_destroy
  labels                     = { app = "auranexus", environment = var.environment }

  dynamic "default_encryption_configuration" {
    for_each = var.kms_key_id == null ? [] : [1]
    content { kms_key_name = var.kms_key_id }
  }
}

resource "google_bigquery_table" "this" {
  for_each            = local.schemas
  dataset_id          = google_bigquery_dataset.analytics.dataset_id
  project             = var.project_id
  table_id            = each.key
  deletion_protection = !var.delete_contents_on_destroy
  schema              = jsonencode(each.value)

  time_partitioning {
    type  = "DAY"
    field = "ts"
  }
  clustering = ["tenant_id", "project_id"]
}

resource "google_bigquery_dataset_iam_member" "writers" {
  for_each   = toset(var.writer_members)
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataEditor"
  member     = each.value
}

resource "google_bigquery_dataset_iam_member" "readers" {
  for_each   = toset(var.reader_members)
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  project    = var.project_id
  role       = "roles/bigquery.dataViewer"
  member     = each.value
}

output "dataset_id" { value = google_bigquery_dataset.analytics.dataset_id }
