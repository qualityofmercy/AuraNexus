variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }

variable "topic_prefix" {
  type        = string
  description = "Must equal AURANEXUS_PUBSUB_TOPIC_PREFIX (the app publishes to <prefix>-events and <prefix>-notifications)."
}

variable "push_endpoint" {
  type        = string
  description = "Full URL of the worker's /internal/pubsub/push endpoint."
}

variable "push_audience" {
  type        = string
  description = "OIDC audience (the worker's base URL)."
}

variable "push_service_account" {
  type        = string
  description = "Email of the SA whose OIDC token Pub/Sub attaches to push requests."
}

variable "scheduler_service_account" { type = string }

variable "publisher_members" {
  type        = list(string)
  description = "serviceAccount:... members allowed to publish events and notifications."
  default     = []
}

variable "schedule_timezone" {
  type    = string
  default = "Asia/Kolkata"
}

variable "weekly_cron" {
  type    = string
  default = "0 8 * * 1" # Mondays 08:00
}

variable "hourly_cron" {
  type    = string
  default = "0 * * * *"
}

variable "max_delivery_attempts" {
  type    = number
  default = 5
}

locals {
  topics = {
    events        = "${var.topic_prefix}-events"
    notifications = "${var.topic_prefix}-notifications"
    dlq           = "${var.topic_prefix}-events-dlq"
  }
  labels = { app = "auranexus", environment = var.environment }
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_pubsub_topic" "this" {
  for_each                   = local.topics
  name                       = each.value
  project                    = var.project_id
  labels                     = local.labels
  message_retention_duration = "604800s"

  # Data residency: messages are only persisted in the deployment region.
  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
}

resource "google_pubsub_subscription" "events_push" {
  name                       = "${var.topic_prefix}-events-push"
  project                    = var.project_id
  topic                      = google_pubsub_topic.this["events"].id
  ack_deadline_seconds       = 600
  message_retention_duration = "604800s"
  labels                     = local.labels

  push_config {
    push_endpoint = var.push_endpoint
    oidc_token {
      service_account_email = var.push_service_account
      audience              = var.push_audience
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.this["dlq"].id
    max_delivery_attempts = var.max_delivery_attempts
  }

  expiration_policy { ttl = "" }
}

# DLQ is pulled by operators (see docs/runbook.md); notifications are pulled by chat/email connectors.
resource "google_pubsub_subscription" "dlq_pull" {
  name                 = "${var.topic_prefix}-events-dlq-pull"
  project              = var.project_id
  topic                = google_pubsub_topic.this["dlq"].id
  ack_deadline_seconds = 60
  labels               = local.labels
  expiration_policy { ttl = "" }
}

resource "google_pubsub_subscription" "notifications_pull" {
  name                 = "${var.topic_prefix}-notifications-pull"
  project              = var.project_id
  topic                = google_pubsub_topic.this["notifications"].id
  ack_deadline_seconds = 60
  labels               = local.labels
  expiration_policy { ttl = "" }
}

# The Pub/Sub service agent forwards undeliverable messages to the DLQ.
locals {
  pubsub_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "dlq_publisher" {
  topic   = google_pubsub_topic.this["dlq"].name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dlq_subscriber" {
  subscription = google_pubsub_subscription.events_push.name
  project      = var.project_id
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

resource "google_pubsub_topic_iam_member" "publishers" {
  for_each = {
    for pair in setproduct(["events", "notifications"], var.publisher_members) :
    "${pair[0]}-${pair[1]}" => { topic = pair[0], member = pair[1] }
  }
  topic   = google_pubsub_topic.this[each.value.topic].name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = each.value.member
}

resource "google_pubsub_topic_iam_member" "scheduler" {
  topic   = google_pubsub_topic.this["events"].name
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.scheduler_service_account}"
}

# Schedule ticks carry no tenant: the orchestrator fans them out to every active project.
resource "google_cloud_scheduler_job" "tick" {
  for_each = {
    weekly = { cron = var.weekly_cron, type = "schedule.weekly" }
    hourly = { cron = var.hourly_cron, type = "schedule.hourly" }
  }
  name      = "${var.topic_prefix}-${each.key}"
  project   = var.project_id
  region    = var.region
  schedule  = each.value.cron
  time_zone = var.schedule_timezone

  pubsub_target {
    topic_name = google_pubsub_topic.this["events"].id
    data       = base64encode(jsonencode({ type = each.value.type }))
  }
  depends_on = [google_pubsub_topic_iam_member.scheduler]
}

output "topic_prefix" { value = var.topic_prefix }
output "events_topic" { value = google_pubsub_topic.this["events"].name }
output "notifications_subscription" { value = google_pubsub_subscription.notifications_pull.name }
output "dlq_subscription" { value = google_pubsub_subscription.dlq_pull.name }
