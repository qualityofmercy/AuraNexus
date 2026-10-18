variable "project_id" { type = string }
variable "region" { type = string }
variable "environment" { type = string }

variable "subnet_cidr" {
  type        = string
  description = "Primary subnet (Cloud Run Direct VPC egress uses this range; size it for peak instances)."
  default     = "10.0.0.0/24"
}

variable "enable_apis" {
  type        = bool
  description = "Enable required Google APIs. Keep true in exactly one module instance per project."
  default     = true
}

# 1. Enable Required GCP APIs (vpcaccess excluded: Cloud Run uses Direct VPC egress, no connector)
locals {
  required_apis = [
    "compute.googleapis.com",
    "run.googleapis.com",
    "sqladmin.googleapis.com",
    "bigquery.googleapis.com",
    "pubsub.googleapis.com",
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudkms.googleapis.com",
    "iam.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudbuild.googleapis.com",
  ]
}

resource "google_project_service" "required_apis" {
  for_each           = var.enable_apis ? toset(local.required_apis) : toset([])
  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}

# 2. Custom VPC
resource "google_compute_network" "vpc" {
  name                    = "auranexus-vpc-${var.environment}"
  project                 = var.project_id
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required_apis]
}

# 3. Subnet for Direct VPC egress; Private Google Access keeps Vertex AI / Pub/Sub traffic off the internet.
resource "google_compute_subnetwork" "subnet" {
  name                     = "auranexus-subnet-${var.environment}"
  project                  = var.project_id
  ip_cidr_range            = var.subnet_cidr
  region                   = var.region
  network                  = google_compute_network.vpc.id
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# 4. Private services access for Cloud SQL (private IP only, no public database endpoint)
resource "google_compute_global_address" "private_services" {
  name          = "auranexus-psa-${var.environment}"
  project       = var.project_id
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 20
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "private_services" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_services.name]
}

# 5. Default-deny ingress; only intra-VPC traffic is allowed (Cloud Run ingress is governed by Cloud Run itself).
resource "google_compute_firewall" "deny_ingress" {
  name      = "auranexus-deny-ingress-${var.environment}"
  project   = var.project_id
  network   = google_compute_network.vpc.name
  direction = "INGRESS"
  priority  = 65000
  deny { protocol = "all" }
  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow_internal" {
  name      = "auranexus-allow-internal-${var.environment}"
  project   = var.project_id
  network   = google_compute_network.vpc.name
  direction = "INGRESS"
  priority  = 1000
  allow { protocol = "tcp" }
  allow { protocol = "udp" }
  allow { protocol = "icmp" }
  source_ranges = [var.subnet_cidr]
}

output "network_id" {
  value = google_compute_network.vpc.id
}

output "network_name" {
  value = google_compute_network.vpc.name
}

output "subnet_id" {
  value = google_compute_subnetwork.subnet.id
}

output "subnet_name" {
  value = google_compute_subnetwork.subnet.name
}

output "private_services_connection" {
  description = "Depend on this before creating Cloud SQL private-IP instances."
  value       = google_service_networking_connection.private_services.id
}
