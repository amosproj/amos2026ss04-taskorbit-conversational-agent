variable "project_id" { type = string }
variable "region" { type = string }
variable "domain" { type = string }

variable "backend_sa_email" { type = string }
variable "worker_sa_email" { type = string }
variable "observability_sa_email" { type = string }

variable "secret_ids" {
  description = "Map of key → Secret Manager secret_id from the secrets module."
  type        = map(string)
}

variable "backend_url" {
  description = "Cloud Run service URL for the backend — used in Prometheus scrape config."
  type        = string
}

variable "worker_url" {
  description = "Cloud Run service URL for the LiveKit worker — used in Prometheus scrape config."
  type        = string
}
