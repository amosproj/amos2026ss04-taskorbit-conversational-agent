variable "enable_gpu_inference" {
  description = "Set to true to deploy the Ollama GCE VM (g2-standard-8 + NVIDIA L4) and GCS model bucket. False is a no-op."
  type        = bool
  default     = false
}

variable "bucket_location" {
  description = "GCS bucket location for Ollama model weights. Kept separate from region so the bucket survives GPU region changes."
  type        = string
  default     = "europe-west4"
}

variable "gpu_inference_models" {
  description = "List of Ollama model tags to pre-populate in the GCS bucket before first deploy."
  type        = list(string)
  default     = ["gemma4:e4b", "gemma4:26b", "qwen3.6:27b", "qwen3.5:9b"]
}

variable "ollama_version" {
  description = "Ollama Docker image tag. Pin to a specific version for reproducible deploys."
  type        = string
  default     = "latest"
}

variable "region" {
  description = "GCP region for the Ollama GCE VM. Must have NVIDIA L4 available."
  type        = string
  default     = "us-east1"
}

variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "zone" {
  description = "GCP zone for the Ollama GCE VM. Must be in var.region and support NVIDIA L4."
  type        = string
  default     = "us-east1-b"
}

variable "preemptible" {
  description = "Use a preemptible (spot) VM to reduce cost. May be terminated by GCP at any time. Set false for stable dev environments."
  type        = bool
  default     = false
}
