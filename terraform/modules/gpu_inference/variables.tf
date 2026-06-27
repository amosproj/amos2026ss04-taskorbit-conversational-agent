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
  description = "GCP region for the Ollama Cloud Run service and GCS model bucket. Must be one of the regions that support NVIDIA L4: asia-southeast1, europe-west1, europe-west4, us-central1, us-east4. Defaults to europe-west4 (Netherlands) when the main stack is in europe-west3."
  type        = string

  validation {
    condition = contains(
      ["asia-southeast1", "europe-west1", "europe-west4", "us-central1", "us-east4"],
      var.region
    )
    error_message = "NVIDIA L4 GPU is only supported in: asia-southeast1, europe-west1, europe-west4, us-central1, us-east4."
  }
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "backend_service_account_email" {
  description = "Email of the backend Cloud Run service account — granted roles/run.invoker on the Ollama service."
  type        = string
}
