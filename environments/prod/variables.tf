variable "project_id" {
  type        = string
  description = "GCP project for the prod environment"
}

variable "region" {
  type    = string
  default = "asia-south1"
}

variable "image" {
  type        = string
  description = "Container image (digest-pinned in prod), e.g. asia-south1-docker.pkg.dev/<proj>/auranexus/auranexus@sha256:..."
}

variable "tenants" {
  type        = map(any)
  description = "Tenant definitions: id => { display_name = ... }"
  default     = {}
}

variable "api_invokers" {
  type        = list(string)
  description = "IAM members that may call the API (group:... / user:...). Never allUsers."
  default     = []
}

variable "dashboard_readers" {
  type    = list(string)
  default = []
}

variable "vertex_region" {
  type    = string
  default = "global"
}

variable "llm_backend" {
  type    = string
  default = "gemini"
}

variable "model" {
  type        = string
  description = "Vertex AI model id (empty = application default for the backend)"
  default     = ""
}

variable "shared_project_id" {
  type        = string
  description = "Project hosting the shared Artifact Registry (defaults to project_id)"
  default     = ""
}

variable "artifact_registry_repository" {
  type    = string
  default = "auranexus"
}

variable "extra_oidc_audiences" {
  type    = list(string)
  default = []
}
