# ── GCP project ──────────────────────────────────────────────────────────────

variable "project_id" {
  description = "GCP project ID where all resources are created."
  type        = string

  validation {
    condition     = length(var.project_id) > 0
    error_message = "project_id must not be empty."
  }
}

variable "region" {
  description = "GCP region for all regional resources."
  type        = string
  default     = "europe-west3"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.region))
    error_message = "region must be a valid GCP region (e.g. europe-west1)."
  }
}

# ── Domain ───────────────────────────────────────────────────────────────────

variable "domain" {
  description = "Root domain (e.g. taskorbit.example.com). Subdomains api. and grafana. are derived automatically."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9][a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$", var.domain))
    error_message = "domain must be a valid hostname (e.g. taskorbit.example.com)."
  }
}

# ── GitHub repository (for Workload Identity) ─────────────────────────────────

variable "github_repository" {
  description = "GitHub repo in owner/name format used to scope Workload Identity (e.g. amosproj/amos2026ss04-taskorbit-conversational-agent)."
  type        = string
  default     = "amosproj/amos2026ss04-taskorbit-conversational-agent"

  validation {
    condition     = can(regex("^[^/]+/[^/]+$", var.github_repository))
    error_message = "github_repository must be in owner/name format (e.g. amosproj/amos2026ss04-taskorbit-conversational-agent)."
  }
}

# ── Container images ─────────────────────────────────────────────────────────

variable "backend_image" {
  description = "Full Artifact Registry image URL for the backend / worker (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/backend:sha-abc1234)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+/.+:.+$", var.backend_image))
    error_message = "backend_image must be a fully qualified image URL with a tag (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/backend:latest)."
  }
}

variable "frontend_image" {
  description = "Full Artifact Registry image URL for the frontend (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/frontend:sha-abc1234)."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9.-]+/.+:.+$", var.frontend_image))
    error_message = "frontend_image must be a fully qualified image URL with a tag (e.g. europe-west1-docker.pkg.dev/PROJECT/taskorbit/frontend:latest)."
  }
}

# ── Cloud Run scaling ─────────────────────────────────────────────────────────

variable "backend_min_instances" {
  description = "Minimum backend Cloud Run instances (≥1 to avoid cold starts)."
  type        = number
  default     = 1

  validation {
    condition     = var.backend_min_instances >= 1 && var.backend_min_instances <= var.backend_max_instances
    error_message = "backend_min_instances must be ≥1 and ≤ backend_max_instances."
  }
}

variable "backend_max_instances" {
  type    = number
  default = 10

  validation {
    condition     = var.backend_max_instances >= 1
    error_message = "backend_max_instances must be ≥1."
  }
}

variable "worker_min_instances" {
  description = "Minimum worker instances — keep at 1 so the LiveKit agent is always listening."
  type        = number
  default     = 1

  validation {
    condition     = var.worker_min_instances >= 0 && var.worker_min_instances <= var.worker_max_instances
    error_message = "worker_min_instances must be ≥0 and ≤ worker_max_instances."
  }
}

variable "worker_max_instances" {
  type    = number
  default = 5

  validation {
    condition     = var.worker_max_instances >= 1
    error_message = "worker_max_instances must be ≥1."
  }
}

variable "frontend_min_instances" {
  type    = number
  default = 1

  validation {
    condition     = var.frontend_min_instances >= 0 && var.frontend_min_instances <= var.frontend_max_instances
    error_message = "frontend_min_instances must be ≥0 and ≤ frontend_max_instances."
  }
}

variable "frontend_max_instances" {
  type    = number
  default = 5

  validation {
    condition     = var.frontend_max_instances >= 1
    error_message = "frontend_max_instances must be ≥1."
  }
}

# ── Application secrets (loaded from terraform.tfvars — never commit) ─────────

variable "livekit_url" {
  description = "LiveKit Cloud WSS URL (wss://…livekit.cloud)."
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.livekit_url, "wss://")
    error_message = "livekit_url must start with wss:// (e.g. wss://your-project.livekit.cloud)."
  }
}

variable "livekit_api_key" {
  type      = string
  sensitive = true

  validation {
    condition     = length(var.livekit_api_key) > 0
    error_message = "livekit_api_key must not be empty."
  }
}

variable "livekit_api_secret" {
  type      = string
  sensitive = true

  validation {
    condition     = length(var.livekit_api_secret) > 0
    error_message = "livekit_api_secret must not be empty."
  }
}

variable "deepgram_api_key" {
  type      = string
  sensitive = true

  validation {
    condition     = length(var.deepgram_api_key) > 0
    error_message = "deepgram_api_key must not be empty."
  }
}

variable "deepgram_model" {
  type    = string
  default = "nova-3"

  validation {
    condition     = length(var.deepgram_model) > 0
    error_message = "deepgram_model must not be empty."
  }
}

variable "deepgram_language" {
  type    = string
  default = "multi"

  validation {
    condition     = length(var.deepgram_language) > 0
    error_message = "deepgram_language must not be empty."
  }
}

variable "elevenlabs_api_key" {
  type      = string
  sensitive = true

  validation {
    condition     = length(var.elevenlabs_api_key) > 0
    error_message = "elevenlabs_api_key must not be empty."
  }
}

variable "elevenlabs_voice_id" {
  type    = string
  default = "21m00Tcm4TlvDq8ikWAM"

  validation {
    condition     = length(var.elevenlabs_voice_id) > 0
    error_message = "elevenlabs_voice_id must not be empty."
  }
}

variable "elevenlabs_model" {
  type    = string
  default = "eleven_multilingual_v2"

  validation {
    condition     = length(var.elevenlabs_model) > 0
    error_message = "elevenlabs_model must not be empty."
  }
}

variable "openai_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "openai_model" {
  type    = string
  default = "gpt-4o-mini"

  validation {
    condition     = length(var.openai_model) > 0
    error_message = "openai_model must not be empty."
  }
}

variable "google_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "google_model" {
  type    = string
  default = "gemini-2.5-flash"

  validation {
    condition     = length(var.google_model) > 0
    error_message = "google_model must not be empty."
  }
}

variable "grafana_admin_password" {
  description = "Grafana admin password stored in Secret Manager."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.grafana_admin_password) >= 12
    error_message = "grafana_admin_password must be at least 12 characters."
  }
}

variable "grafana_admin_user" {
  description = "Grafana admin username stored in Secret Manager."
  type        = string
  sensitive   = true
  default     = "admin"

  validation {
    condition     = length(var.grafana_admin_user) > 0
    error_message = "grafana_admin_user must not be empty."
  }
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

variable "api_url_override" {
  description = "Override VITE_API_URL for the frontend — set to the backend Cloud Run URL when no domain/LB is configured. Leave empty to use https://api.<domain>."
  type        = string
  default     = ""
}
