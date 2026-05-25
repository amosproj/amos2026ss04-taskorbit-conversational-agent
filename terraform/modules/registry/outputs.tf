output "repository_url" {
  description = "Docker repository root URL — prefix image names with this."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.docker.repository_id}"
}
