locals {
  # Maps secret key (used as suffix in the Secret Manager ID) to its value.
  # Keys that are truly optional (empty string) are still provisioned so Cloud
  # Run env var references never break — the empty string is a valid secret value.
  app_secrets = {
    "livekit-url"           = var.livekit_url
    "livekit-api-key"       = var.livekit_api_key
    "livekit-api-secret"    = var.livekit_api_secret
    "deepgram-api-key"      = var.deepgram_api_key
    "deepgram-model"        = var.deepgram_model
    "deepgram-language"     = var.deepgram_language
    "elevenlabs-api-key"    = var.elevenlabs_api_key
    "elevenlabs-voice-id"   = var.elevenlabs_voice_id
    "elevenlabs-model"      = var.elevenlabs_model
    "openai-api-key"        = var.openai_api_key
    "openai-model"          = var.openai_model
    "google-api-key"        = var.google_api_key
    "google-model"          = var.google_model
    "openrouter-api-key"    = var.openrouter_api_key
    "openrouter-model"      = var.openrouter_model
    "database-url"          = var.database_url
    "grafana-admin-password" = var.grafana_admin_password
    "grafana-admin-user"     = var.grafana_admin_user
    "auth-enabled"           = var.auth_enabled
    "secret-key"             = var.secret_key
  }
}

resource "google_secret_manager_secret" "secrets" {
  for_each = local.app_secrets

  secret_id = "taskorbit-${each.key}"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    managed-by = "terraform"
    app        = "taskorbit"
  }
}

resource "google_secret_manager_secret_version" "versions" {
  for_each = local.app_secrets

  secret      = google_secret_manager_secret.secrets[each.key].id
  secret_data = each.value

  # Allow manual key rotation (e.g. rolling API keys) without Terraform drift.
  # To force an update, use `terraform taint` on the specific version resource.
  lifecycle {
    ignore_changes = [secret_data]
  }
}
