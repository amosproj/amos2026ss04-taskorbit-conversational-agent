variable "project_id" { type = string }
variable "region" { type = string }
variable "domain" { type = string }

variable "backend_image" { type = string }
variable "frontend_image" { type = string }

variable "backend_sa_email" { type = string }
variable "worker_sa_email" { type = string }
variable "frontend_sa_email" { type = string }

variable "vpc_connector_id" { type = string }
variable "cloud_sql_connection_name" { type = string }

variable "secret_ids" {
  description = "Map of key → Secret Manager secret_id produced by the secrets module."
  type        = map(string)
}

variable "backend_min_instances" {
  type    = number
  default = 1
}

variable "backend_max_instances" {
  type    = number
  default = 10
}

variable "worker_min_instances" {
  type    = number
  default = 1
}

variable "worker_max_instances" {
  type    = number
  default = 5
}

variable "frontend_min_instances" {
  type    = number
  default = 1
}

variable "frontend_max_instances" {
  type    = number
  default = 5
}

variable "cors_allow_origins" {
  type    = string
  default = ""
}

variable "api_url_override" {
  description = "Override VITE_API_URL for the frontend — use the backend Cloud Run URL when no domain/LB is configured."
  type        = string
  default     = ""
}
