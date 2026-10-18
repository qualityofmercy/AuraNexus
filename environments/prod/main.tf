terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  backend "gcs" {
    bucket = "auranexus-terraform-state-store"
    prefix = "prod"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "stack" {
  source      = "../../modules/auranexus-env"
  project_id  = var.project_id
  region      = var.region
  environment = "prod"
  image       = var.image
  tenants     = var.tenants

  subnet_cidr          = "10.20.0.0/24"
  api_invokers         = var.api_invokers
  extra_oidc_audiences = var.extra_oidc_audiences
  dashboard_readers    = var.dashboard_readers
  vertex_region        = var.vertex_region
  llm_backend          = var.llm_backend
  model                = var.model
  protect_data         = true
  db_high_availability = true
  api_scaling          = { min = 1, max = 5 }
  worker_scaling       = { min = 1, max = 10 }

  artifact_registry = {
    project    = var.shared_project_id != "" ? var.shared_project_id : var.project_id
    location   = var.region
    repository = var.artifact_registry_repository
  }
}
