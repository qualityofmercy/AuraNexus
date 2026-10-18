# Composite module: one complete AuraNexus environment (dev or prod). Environments differ only in inputs,
# so dev and prod cannot drift apart structurally.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }
variable "image" { type = string }

variable "tenants" {
  type        = map(any)
  description = "Tenant id => { display_name, admin_email }. admin_email becomes the tenant admin+PM when the migration job runs. Tenants share the stack; data is isolated by RLS and GCS prefixes."
  default     = {}
}

variable "subnet_cidr" {
  type    = string
  default = "10.10.0.0/24"
}

variable "enable_apis" {
  type    = bool
  default = true
}

variable "vertex_region" {
  type        = string
  description = "Vertex AI location. 'global' maximises availability; use a regional location (e.g. asia-south1) when data residency requires it and the chosen model is served there."
  default     = "global"
}

variable "llm_backend" {
  type        = string
  description = "gemini (default) or claude, both served from Vertex AI in this project."
  default     = "gemini"
  validation {
    condition     = contains(["gemini", "claude"], var.llm_backend)
    error_message = "llm_backend must be gemini or claude."
  }
}

variable "model" {
  type        = string
  description = "Vertex AI model id. Empty = application default for the backend. Confirm availability/quota in your region first."
  default     = ""
}

variable "api_invokers" {
  type        = list(string)
  description = "IAM members allowed to call the API (e.g. group:pmo@example.com). Never allUsers."
  default     = []
}

variable "extra_oidc_audiences" {
  type        = list(string)
  description = "Additional accepted token audiences (dev only: the gcloud CLI client id lets a developer use their own login)."
  default     = []
}

variable "dashboard_readers" {
  type    = list(string)
  default = []
}

variable "db_tier" {
  type    = string
  default = "db-custom-2-7680"
}

variable "db_high_availability" {
  type    = bool
  default = false
}

variable "protect_data" {
  type        = bool
  description = "Deletion protection on database, Cloud Run, BigQuery. True for prod."
  default     = true
}

variable "api_scaling" {
  type    = object({ min = number, max = number })
  default = { min = 0, max = 5 }
}

variable "worker_scaling" {
  type    = object({ min = number, max = number })
  default = { min = 0, max = 10 }
}

variable "schedule_timezone" {
  type    = string
  default = "Asia/Kolkata"
}

variable "artifact_registry" {
  description = "Shared Artifact Registry repo hosting the image (granted to the Cloud Run service agent)."
  type = object({
    project    = string
    location   = string
    repository = string
  })
  default = null
}

locals {
  topic_prefix = "auranexus-${var.environment}"
}

data "google_project" "this" {
  project_id = var.project_id
}

module "networking" {
  source      = "../gcp-networking"
  project_id  = var.project_id
  region      = var.region
  environment = var.environment
  subnet_cidr = var.subnet_cidr
  enable_apis = var.enable_apis
}

module "iam" {
  source      = "../gcp-iam"
  project_id  = var.project_id
  environment = var.environment
  depends_on  = [module.networking]
}

module "storage" {
  source         = "../gcp-storage"
  project_id     = var.project_id
  region         = var.region
  environment    = var.environment
  tenants        = var.tenants
  writer_members = [module.iam.members["api"], module.iam.members["worker"]]
  force_destroy  = !var.protect_data
  depends_on     = [module.networking]
}

module "database" {
  source                      = "../gcp-database"
  project_id                  = var.project_id
  region                      = var.region
  environment                 = var.environment
  network_id                  = module.networking.network_id
  private_services_connection = module.networking.private_services_connection
  tier                        = var.db_tier
  high_availability           = var.db_high_availability
  deletion_protection         = var.protect_data
  secret_accessors            = [module.iam.members["api"], module.iam.members["worker"]]
  migrator_members            = [module.iam.members["migrator"]]
}

module "bigquery" {
  source                     = "../gcp-bigquery"
  project_id                 = var.project_id
  region                     = var.region
  environment                = var.environment
  writer_members             = [module.iam.members["api"], module.iam.members["worker"]]
  reader_members             = var.dashboard_readers
  delete_contents_on_destroy = !var.protect_data
  depends_on                 = [module.networking]
}

module "pubsub" {
  source                    = "../gcp-pubsub"
  project_id                = var.project_id
  region                    = var.region
  environment               = var.environment
  topic_prefix              = local.topic_prefix
  push_endpoint             = "${module.cloud_run.urls["worker"]}/internal/pubsub/push"
  push_audience             = module.cloud_run.urls["worker"]
  push_service_account      = module.iam.emails["pubsub"]
  scheduler_service_account = module.iam.emails["scheduler"]
  publisher_members         = [module.iam.members["api"], module.iam.members["worker"]]
  schedule_timezone         = var.schedule_timezone
  depends_on                = [module.networking]
}

module "cloud_run" {
  source              = "../gcp-cloud-run"
  project_id          = var.project_id
  region              = var.region
  environment         = var.environment
  image               = var.image
  network_name        = module.networking.network_name
  subnet_name         = module.networking.subnet_name
  deletion_protection = var.protect_data

  services = {
    api = {
      service_account = module.iam.emails["api"]
      ingress         = "INGRESS_TRAFFIC_ALL"
      invokers        = var.api_invokers
      min_instances   = var.api_scaling.min
      max_instances   = var.api_scaling.max
      cpu             = "1"
      memory          = "1Gi"
      concurrency     = 40
      timeout_seconds = 300
    }
    worker = {
      service_account = module.iam.emails["worker"]
      ingress         = "INGRESS_TRAFFIC_INTERNAL_ONLY"
      invokers        = [module.iam.members["pubsub"]]
      min_instances   = var.worker_scaling.min
      max_instances   = var.worker_scaling.max
      cpu             = "2"
      memory          = "2Gi"
      concurrency     = 4 # agent runs wait on the LLM; keep per-instance fan-in low
      timeout_seconds = 900
    }
  }

  env_vars = {
    AURANEXUS_ENV                       = var.environment
    AURANEXUS_HOME                      = "/app"
    AURANEXUS_STORE_BACKEND             = "postgres"
    AURANEXUS_LLM_BACKEND               = var.llm_backend
    AURANEXUS_GCP_PROJECT               = var.project_id
    AURANEXUS_VERTEX_REGION             = var.vertex_region
    AURANEXUS_MODEL                     = var.model
    AURANEXUS_BUS_BACKEND               = "pubsub"
    AURANEXUS_PUBSUB_TOPIC_PREFIX       = local.topic_prefix
    AURANEXUS_ANALYTICS_BACKEND         = "bigquery"
    AURANEXUS_BIGQUERY_DATASET          = module.bigquery.dataset_id
    AURANEXUS_AUTH_MODE                 = "oidc"
    AURANEXUS_OIDC_EXTRA_AUDIENCES      = jsonencode(var.extra_oidc_audiences)
    AURANEXUS_INTERNAL_SERVICE_ACCOUNTS = jsonencode([module.iam.emails["pubsub"], module.iam.emails["scheduler"]])
  }

  # The API exposes no /internal routes. Only the worker (invokers = the Pub/Sub SA, internal ingress) trusts
  # Cloud Run IAM for internal callers, because Cloud Run redacts the token signature it has already validated.
  service_env_vars = {
    api    = { AURANEXUS_ENABLE_INTERNAL = "false" }
    worker = { AURANEXUS_TRUST_EDGE_IAM = "true" }
  }

  secret_env_vars = {
    AURANEXUS_DATABASE_URL = module.database.app_url_secret_id
  }

  migration_job = {
    service_account  = module.iam.emails["migrator"]
    owner_url_secret = module.database.owner_url_secret_id
    bootstrap        = jsonencode({ for k, v in var.tenants : k => try(v.admin_email, "") })
  }

  depends_on = [module.database]
}

# Let Cloud Run pull the image from the shared registry.
resource "google_artifact_registry_repository_iam_member" "pull" {
  count      = var.artifact_registry == null ? 0 : 1
  project    = var.artifact_registry.project
  location   = var.artifact_registry.location
  repository = var.artifact_registry.repository
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.this.number}@serverless-robot-prod.iam.gserviceaccount.com"
}

output "api_url" { value = module.cloud_run.urls["api"] }
output "worker_url" { value = module.cloud_run.urls["worker"] }
output "migration_job" { value = module.cloud_run.migration_job }
output "database_instance" { value = module.database.instance_name }
output "bucket" { value = module.storage.bucket_name }
output "analytics_dataset" { value = module.bigquery.dataset_id }
output "service_accounts" { value = module.iam.emails }
output "notifications_subscription" { value = module.pubsub.notifications_subscription }
output "dlq_subscription" { value = module.pubsub.dlq_subscription }
