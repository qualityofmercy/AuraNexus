variable "project_id" { type = string }
variable "environment" { type = string }

# One identity per concern (least privilege). Resource-level grants live in the module owning the resource.
locals {
  accounts = {
    api       = "Serves the HITL API and event ingest"
    worker    = "Runs agents (Pub/Sub push target)"
    pubsub    = "Signs Pub/Sub push OIDC tokens to the worker"
    scheduler = "Cloud Scheduler publisher"
    migrator  = "Runs database migrations"
  }

  project_roles = {
    api      = ["roles/aiplatform.user", "roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"]
    worker   = ["roles/aiplatform.user", "roles/logging.logWriter", "roles/monitoring.metricWriter", "roles/cloudtrace.agent"]
    migrator = ["roles/logging.logWriter"]
  }

  bindings = merge([
    for acct, roles in local.project_roles : {
      for r in roles : "${acct}-${r}" => { account = acct, role = r }
    }
  ]...)
}

resource "google_service_account" "this" {
  for_each     = local.accounts
  project      = var.project_id
  account_id   = "auranexus-${each.key}-${var.environment}"
  display_name = "AuraNexus ${each.key} (${var.environment})"
  description  = each.value
}

resource "google_project_iam_member" "roles" {
  for_each = local.bindings
  project  = var.project_id
  role     = each.value.role
  member   = "serviceAccount:${google_service_account.this[each.value.account].email}"
}

output "emails" {
  value = { for k, v in google_service_account.this : k => v.email }
}

output "members" {
  value = { for k, v in google_service_account.this : k => "serviceAccount:${v.email}" }
}
