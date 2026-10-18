terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
  backend "gcs" {
    bucket = "auranexus-terraform-state-store"
    prefix = "shared-services"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" {
  type        = string
  description = "GCP Project ID for AuraNexus shared services"
}

variable "region" {
  type    = string
  default = "asia-south1" # Close to Mumbai region
}

variable "image_retention_count" {
  type        = number
  description = "Keep this many most-recent image versions per package."
  default     = 30
}

module "networking" {
  source      = "../../modules/gcp-networking"
  project_id  = var.project_id
  region      = var.region
  environment = "shared"
}

# Container images for every environment. Immutable tags: a tag can never be silently repointed.
resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = "auranexus"
  format        = "DOCKER"
  description   = "AuraNexus API/worker images"

  docker_config {
    immutable_tags = true
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = var.image_retention_count
    }
  }

  depends_on = [module.networking]
}

output "vpc_output" {
  value = module.networking.network_id
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
