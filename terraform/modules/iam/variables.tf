variable "project_id" { type = string }
variable "github_repository" { type = string }

variable "secret_ids" {
  description = "Map of secret key → Secret Manager secret_id (short form). Used for resource-scoped secretAccessor bindings."
  type        = map(string)
}
