variable "enable_gpu_inference" {
  description = "Set to true to deploy the Ollama Cloud Run service and GCS model bucket. False is a no-op."
  type        = bool
  default     = false
}

variable "min_instances" {
  description = "Minimum Cloud Run instances. 0 = scale to zero (cheapest); 1 = always warm (avoids 60-120s GPU cold start)."
  type        = number
  default     = 0
}

variable "gpu_inference_models" {
  description = "List of Ollama model tags to pre-populate in the GCS bucket before first deploy."
  type        = list(string)
  default     = ["gemma4:e4b", "gemma4:26b", "qwen3.6:27b"]
}

variable "ollama_version" {
  description = "Ollama Docker image tag. Pin to a specific version for reproducible deploys."
  type        = string
  default     = "latest"
}

variable "region" {
  description = "GCP region for the Cloud Run service and GCS bucket."
  type        = string
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "backend_service_account_email" {
  description = "Email of the backend Cloud Run service account — granted roles/run.invoker on the Ollama service."
  type        = string
}
