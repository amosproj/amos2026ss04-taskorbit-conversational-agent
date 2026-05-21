# ── GCP project ──────────────────────────────────────────────────────────────

variable "project_id" {
  description = "GCP project ID where all resources are created."
  type        = string
}

variable "region" {
  description = "GCP region for all regional resources."
  type        = string
  default     = "europe-west1"
}

# ── Domain ───────────────────────────────────────────────────────────────────

variable "domain" {
  description = "Root domain (e.g. taskorbit.example.com). Subdomains api. and grafana. are derived automatically."
  type        = string
}

# ── GitHub repository (for Workload Identity) ─────────────────────────────────

variable "github_repository" {
  description = "GitHub repo in owner/name format used to scope Workload Identity (e.g. amosproj/amos2026ss04-taskorbit-conversational-agent)."
  type        = string
  default     = "amosproj/amos2026ss04-taskorbit-conversational-agent"
}

# ── Container images ─────────────────────────────────────────────────────────

variable "backend_image" {
  description = "Full Artifact Registry image URL for the backend / worker (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/backend:sha-abc1234)."
  type        = string
}

variable "frontend_image" {
  description = "Full Artifact Registry image URL for the frontend (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/frontend:sha-abc1234)."
  type        = string
}

# ── Cloud Run scaling ─────────────────────────────────────────────────────────

variable "backend_min_instances" {
  description = "Minimum backend Cloud Run instances (≥1 to avoid cold starts)."
  type        = number
  default     = 1
}

variable "backend_max_instances" {
  type    = number
  default = 10
}

variable "worker_min_instances" {
  description = "Minimum worker instances — keep at 1 so the LiveKit agent is always listening."
  type        = number
  default     = 1
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

# ── Application secrets (loaded from terraform.tfvars — never commit) ─────────

variable "livekit_url" {
  description = "LiveKit Cloud WSS URL (wss://…livekit.cloud)."
  type        = string
  sensitive   = true
}

variable "livekit_api_key" {
  type      = string
  sensitive = true
}

variable "livekit_api_secret" {
  type      = string
  sensitive = true
}

variable "deepgram_api_key" {
  type      = string
  sensitive = true
}

variable "deepgram_model" {
  type    = string
  default = "nova-3"
}

variable "deepgram_language" {
  type    = string
  default = "multi"
}

variable "elevenlabs_api_key" {
  type      = string
  sensitive = true
}

variable "elevenlabs_voice_id" {
  type    = string
  default = "21m00Tcm4TlvDq8ikWAM"
}

variable "elevenlabs_model" {
  type    = string
  default = "eleven_multilingual_v2"
}

variable "openai_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "openai_model" {
  type    = string
  default = "gpt-4o-mini"
}

variable "google_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_model" {
  type    = string
  default = "gemini-2.5-flash"
}

variable "grafana_admin_password" {
  description = "Grafana admin password stored in Secret Manager."
  type        = string
  sensitive   = true
}

# ── Observability ─────────────────────────────────────────────────────────────

variable "enable_auto_shutdown" {
  description = "Enable Cloud Scheduler jobs to stop Cloud SQL and (optionally) scale down the worker outside business hours."
  type        = bool
  default     = true
}

variable "scale_worker_overnight" {
  description = "Scale the LiveKit worker to 0 overnight. Saves cost but drops active voice rooms. Only enable when 24/7 availability is not required."
  type        = bool
  default     = false
}

variable "cors_allow_origins" {
  description = "Comma-separated list of origins allowed by the FastAPI CORS middleware."
  type        = string
  default     = ""
}
