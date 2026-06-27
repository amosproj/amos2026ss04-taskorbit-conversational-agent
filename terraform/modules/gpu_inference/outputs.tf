output "ollama_service_url" {
  description = "HTTPS URL of the Ollama Cloud Run service. Stable across redeployments — use as OLLAMA_BASE_URL in backend/worker Cloud Run env vars."
  value       = var.enable_gpu_inference ? google_cloud_run_v2_service.ollama[0].uri : ""
}

output "ollama_models_bucket" {
  description = "GCS bucket name where Ollama model weights are stored. Pre-populate before first deploy."
  value       = var.enable_gpu_inference ? google_storage_bucket.ollama_models[0].name : ""
}

output "ollama_sa_email" {
  description = "Service account email for the Ollama Cloud Run service."
  value       = var.enable_gpu_inference ? google_service_account.ollama_sa[0].email : ""
}
