variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }

variable "tenants" {
  type        = map(any)
  description = "Tenant id => settings. Each tenant gets its own object prefix."
  default     = {}
}

variable "writer_members" {
  type        = list(string)
  description = "IAM members (serviceAccount:...) that read/write objects."
  default     = []
}

variable "force_destroy" {
  type    = bool
  default = false
}

variable "kms_rotation_period" {
  type    = string
  default = "7776000s" # 90 days
}

# Customer-managed encryption key for transcripts, exports and attachments.
resource "google_kms_key_ring" "this" {
  name     = "auranexus-${var.environment}"
  project  = var.project_id
  location = var.region
}

resource "google_kms_crypto_key" "storage" {
  name            = "storage"
  key_ring        = google_kms_key_ring.this.id
  rotation_period = var.kms_rotation_period
  lifecycle { prevent_destroy = true }
}

data "google_storage_project_service_account" "gcs" {
  project = var.project_id
}

resource "google_kms_crypto_key_iam_member" "gcs" {
  crypto_key_id = google_kms_crypto_key.storage.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${data.google_storage_project_service_account.gcs.email_address}"
}

resource "google_storage_bucket" "artifacts" {
  name                        = "${var.project_id}-auranexus-${var.environment}"
  project                     = var.project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy

  versioning { enabled = true }

  encryption { default_kms_key_name = google_kms_crypto_key.storage.id }

  lifecycle_rule {
    condition { num_newer_versions = 5 }
    action { type = "Delete" }
  }
  lifecycle_rule {
    condition {
      age        = 30
      with_state = "ARCHIVED"
    }
    action { type = "Delete" }
  }

  labels     = { app = "auranexus", environment = var.environment }
  depends_on = [google_kms_crypto_key_iam_member.gcs]
}

# Tenant prefixes (tenant/<id>/transcripts, exports, ...). Objects are namespaced, never shared across tenants.
resource "google_storage_bucket_object" "tenant_prefix" {
  for_each = var.tenants
  bucket   = google_storage_bucket.artifacts.name
  name     = "tenants/${each.key}/.keep"
  content  = "tenant prefix"
}

resource "google_storage_bucket_iam_member" "writers" {
  for_each = toset(var.writer_members)
  bucket   = google_storage_bucket.artifacts.name
  role     = "roles/storage.objectUser"
  member   = each.value
}

output "bucket_name" { value = google_storage_bucket.artifacts.name }
output "kms_key_id" { value = google_kms_crypto_key.storage.id }
