output "backend_sa_email" {
  value = google_service_account.backend.email
}

output "worker_sa_email" {
  value = google_service_account.worker.email
}

output "frontend_sa_email" {
  value = google_service_account.frontend.email
}

output "observability_sa_email" {
  value = google_service_account.observability.email
}

output "cicd_sa_email" {
  value = google_service_account.cicd.email
}

output "workload_identity_provider" {
  description = "Full provider resource name — set as GCP_WORKLOAD_IDENTITY_PROVIDER in GitHub Actions secrets."
  value       = google_iam_workload_identity_pool_provider.github.name
}
