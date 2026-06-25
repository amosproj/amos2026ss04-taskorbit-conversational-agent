variable "project_id" {
  type = string
}

variable "livekit_url" {
  type      = string
  sensitive = true
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
  type = string
}

variable "deepgram_language" {
  type = string
}

variable "elevenlabs_api_key" {
  type      = string
  sensitive = true
}

variable "elevenlabs_voice_id" {
  type = string
}

variable "elevenlabs_model" {
  type = string
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

variable "openrouter_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "openrouter_model" {
  type    = string
  default = "meta-llama/llama-3.1-8b-instruct:free"
}

variable "database_url" {
  type      = string
  sensitive = true
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
}

variable "grafana_admin_user" {
  type      = string
  sensitive = true
}
