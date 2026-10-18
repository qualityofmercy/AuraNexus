variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }
variable "network_id" { type = string }

variable "private_services_connection" {
  type        = string
  description = "Output of gcp-networking; guarantees private services access exists before the instance."
}

variable "tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "high_availability" {
  type    = bool
  default = false
}

variable "deletion_protection" {
  type    = bool
  default = true
}

variable "disk_size_gb" {
  type    = number
  default = 20
}

variable "backup_retention_days" {
  type    = number
  default = 14
}

variable "secret_accessors" {
  type        = list(string)
  description = "serviceAccount:... members that may read the app database URL secret."
  default     = []
}

variable "migrator_members" {
  type        = list(string)
  description = "serviceAccount:... members that may read the owner database URL secret."
  default     = []
}

resource "random_id" "suffix" {
  byte_length = 3
}

resource "google_sql_database_instance" "this" {
  name                = "auranexus-${var.environment}-${random_id.suffix.hex}"
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection

  settings {
    tier                        = var.tier
    edition                     = "ENTERPRISE"
    availability_type           = var.high_availability ? "REGIONAL" : "ZONAL"
    disk_size                   = var.disk_size_gb
    disk_autoresize             = true
    deletion_protection_enabled = var.deletion_protection

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_id
      ssl_mode        = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
      start_time                     = "21:00"
      transaction_log_retention_days = 7
      backup_retention_settings { retained_backups = var.backup_retention_days }
    }

    maintenance_window {
      day          = 7
      hour         = 22
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled = true
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }
    database_flags {
      name  = "log_connections"
      value = "on"
    }
    database_flags {
      name  = "log_min_duration_statement"
      value = "1000"
    }

    user_labels = { app = "auranexus", environment = var.environment }
  }

  depends_on = [var.private_services_connection]
}

resource "google_sql_database" "app" {
  name     = "auranexus"
  project  = var.project_id
  instance = google_sql_database_instance.this.name
}

# Two logins: the owner runs migrations (creates tables, owns them); the app user is NOT the owner and has
# NOBYPASSRLS (set by migrations/001_init.sql), so row-level tenant isolation cannot be bypassed by the app.
resource "random_password" "app" {
  length  = 32
  special = false
}

resource "random_password" "owner" {
  length  = 32
  special = false
}

resource "google_sql_user" "app" {
  name     = "auranexus_app"
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.app.result
}

resource "google_sql_user" "owner" {
  name     = "auranexus_owner"
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.owner.result
}

locals {
  host = google_sql_database_instance.this.private_ip_address
}

resource "google_secret_manager_secret" "app_url" {
  secret_id = "auranexus-${var.environment}-database-url"
  project   = var.project_id
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

resource "google_secret_manager_secret_version" "app_url" {
  secret      = google_secret_manager_secret.app_url.id
  secret_data = "postgresql+psycopg://${google_sql_user.app.name}:${random_password.app.result}@${local.host}:5432/${google_sql_database.app.name}?sslmode=require"
}

resource "google_secret_manager_secret" "owner_url" {
  secret_id = "auranexus-${var.environment}-database-owner-url"
  project   = var.project_id
  replication {
    user_managed {
      replicas { location = var.region }
    }
  }
}

resource "google_secret_manager_secret_version" "owner_url" {
  secret      = google_secret_manager_secret.owner_url.id
  secret_data = "postgresql+psycopg://${google_sql_user.owner.name}:${random_password.owner.result}@${local.host}:5432/${google_sql_database.app.name}?sslmode=require"
}

resource "google_secret_manager_secret_iam_member" "app" {
  for_each  = toset(var.secret_accessors)
  secret_id = google_secret_manager_secret.app_url.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}

resource "google_secret_manager_secret_iam_member" "owner" {
  for_each  = toset(var.migrator_members)
  secret_id = google_secret_manager_secret.owner_url.id
  project   = var.project_id
  role      = "roles/secretmanager.secretAccessor"
  member    = each.value
}

output "instance_name" { value = google_sql_database_instance.this.name }
output "private_ip" { value = local.host }
output "app_url_secret_id" { value = google_secret_manager_secret.app_url.secret_id }
output "owner_url_secret_id" { value = google_secret_manager_secret.owner_url.secret_id }
