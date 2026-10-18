terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 7.0" # deletion_protection on Cloud Run v2 resources needs provider 6.x
    }
  }
}

variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }
variable "image" { type = string }
variable "network_name" { type = string }
variable "subnet_name" { type = string }

variable "services" {
  description = <<-EOT
    Cloud Run services. Same image, different exposure:
      api    - HITL API + event ingest; ingress ALL but IAM-authenticated (no allUsers)
      worker - Pub/Sub push target running agents; ingress internal only
  EOT
  type = map(object({
    service_account = string
    ingress         = string # INGRESS_TRAFFIC_ALL | INGRESS_TRAFFIC_INTERNAL_ONLY | INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER
    invokers        = list(string)
    min_instances   = number
    max_instances   = number
    cpu             = string
    memory          = string
    concurrency     = number
    timeout_seconds = number
  }))
}

variable "env_vars" {
  type        = map(string)
  description = "Plain environment variables shared by all services."
  default     = {}
}

variable "service_env_vars" {
  type        = map(map(string))
  description = "Per-service environment variables (service name => vars), merged over env_vars."
  default     = {}
}

variable "secret_env_vars" {
  type        = map(string)
  description = "ENV_NAME => Secret Manager secret id (latest version)."
  default     = {}
}

variable "migration_job" {
  type = object({
    service_account  = string
    owner_url_secret = string
    bootstrap        = string # JSON {"tenant": "admin@email"} seeded after migrations
  })
  description = "Cloud Run job that applies migrations/*.sql as the database owner."
  default     = null
}

variable "deletion_protection" {
  type    = bool
  default = true
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  # Cloud Run v2 deterministic URL (also used as OIDC audience / Pub/Sub push target).
  urls = {
    for name in keys(var.services) :
    name => "https://auranexus-${name}-${var.environment}-${data.google_project.this.number}.${var.region}.run.app"
  }
}

resource "google_cloud_run_v2_service" "this" {
  for_each            = var.services
  name                = "auranexus-${each.key}-${var.environment}"
  project             = var.project_id
  location            = var.region
  ingress             = each.value.ingress
  deletion_protection = var.deletion_protection
  labels              = { app = "auranexus", environment = var.environment, role = each.key }

  template {
    service_account                  = each.value.service_account
    timeout                          = "${each.value.timeout_seconds}s"
    max_instance_request_concurrency = each.value.concurrency

    scaling {
      min_instance_count = each.value.min_instances
      max_instance_count = each.value.max_instances
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY" # Vertex AI / Pub/Sub use Private Google Access; the database is private IP
      network_interfaces {
        network    = var.network_name
        subnetwork = var.subnet_name
      }
    }

    containers {
      image = var.image

      resources {
        limits = { cpu = each.value.cpu, memory = each.value.memory }
      }

      ports { container_port = 8080 }

      dynamic "env" {
        for_each = merge(var.env_vars, lookup(var.service_env_vars, each.key, {}), {
          AURANEXUS_OIDC_AUDIENCE = local.urls[each.key]
        })
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env_vars
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get { path = "/healthz" }
        initial_delay_seconds = 2
        period_seconds        = 5
        failure_threshold     = 12
      }
      liveness_probe {
        http_get { path = "/healthz" }
        period_seconds = 30
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # CI/CD (cloudbuild.yaml) rolls out new images with `gcloud run services update --image`;
  # Terraform owns everything else and must not revert the image on the next apply.
  lifecycle {
    ignore_changes = [template[0].containers[0].image, scaling, client, client_version]
  }
}

# Authenticated invocation only. There is intentionally no allUsers binding anywhere.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = {
    for pair in flatten([
      for name, svc in var.services : [for m in svc.invokers : { key = "${name}-${m}", name = name, member = m }]
    ]) : pair.key => pair
  }
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this[each.value.name].name
  role     = "roles/run.invoker"
  member   = each.value.member
}

resource "google_cloud_run_v2_job" "migrate" {
  count               = var.migration_job == null ? 0 : 1
  name                = "auranexus-migrate-${var.environment}"
  project             = var.project_id
  location            = var.region
  deletion_protection = var.deletion_protection

  lifecycle {
    ignore_changes = [template[0].template[0].containers[0].image, client, client_version]
  }

  template {
    template {
      service_account = var.migration_job.service_account
      max_retries     = 1
      timeout         = "600s"

      vpc_access {
        egress = "PRIVATE_RANGES_ONLY"
        network_interfaces {
          network    = var.network_name
          subnetwork = var.subnet_name
        }
      }

      containers {
        image   = var.image
        command = ["python", "-m", "auranexus.migrate"]
        env {
          name  = "AURANEXUS_BOOTSTRAP_TENANTS"
          value = var.migration_job.bootstrap
        }
        env {
          name = "AURANEXUS_MIGRATION_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = var.migration_job.owner_url_secret
              version = "latest"
            }
          }
        }
      }
    }
  }
}

output "urls" { value = local.urls }
output "service_names" { value = { for k, v in google_cloud_run_v2_service.this : k => v.name } }
output "migration_job" { value = try(google_cloud_run_v2_job.migrate[0].name, null) }
