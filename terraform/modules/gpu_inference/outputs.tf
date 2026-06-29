output "ollama_service_url" {
  description = "HTTP URL of the Ollama GCE VM. Use as OLLAMA_BASE_URL in backend/worker env vars."
  value       = var.enable_gpu_inference ? "http://${google_compute_address.ollama_ip[0].address}:11434" : ""
}

output "ollama_models_bucket" {
  description = "GCS bucket name where Ollama model weights are stored."
  value       = var.enable_gpu_inference ? google_storage_bucket.ollama_models[0].name : ""
}

output "ollama_sa_email" {
  description = "Service account email for the Ollama GCE VM."
  value       = var.enable_gpu_inference ? google_service_account.ollama_sa[0].email : ""
}

output "ollama_vm_ip" {
  description = "Static external IP of the Ollama GCE VM."
  value       = var.enable_gpu_inference ? google_compute_address.ollama_ip[0].address : ""
}
