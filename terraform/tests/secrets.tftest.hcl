# Tests for modules/secrets
#
# Verifies that all secrets are created with the correct taskorbit- prefix
# and that the secret_ids output map contains the expected keys.

mock_provider "google" {}

variables {
  project_id             = "test-project"
  livekit_url            = "wss://test.livekit.cloud"
  livekit_api_key        = "test-api-key"
  livekit_api_secret     = "test-api-secret"
  deepgram_api_key       = "test-deepgram-key"
  deepgram_model         = "nova-3"
  deepgram_language      = "multi"
  elevenlabs_api_key     = "test-elevenlabs-key"
  elevenlabs_voice_id    = "21m00Tcm4TlvDq8ikWAM"
  elevenlabs_model       = "eleven_multilingual_v2"
  openai_api_key         = "test-openai-key"
  openai_model           = "gpt-4o-mini"
  google_api_key         = "test-google-key"
  google_model           = "gemini-2.5-flash"
  database_url           = "postgresql://taskorbit:pass@/taskorbit"
  grafana_admin_password = "test-grafana-password"
  grafana_admin_user     = "test-admin"
}

# ── All 16 secrets are created ────────────────────────────────────────────────

run "creates_all_16_secrets" {
  command = plan

  module {
    source = "./modules/secrets"
  }

  assert {
    condition     = length(google_secret_manager_secret.secrets) == 16
    error_message = "Expected exactly 16 Secret Manager secrets."
  }
}

# ── Secret IDs use the taskorbit- prefix ──────────────────────────────────────

run "all_secret_ids_have_taskorbit_prefix" {
  command = plan

  module {
    source = "./modules/secrets"
  }

  assert {
    condition = alltrue([
      for k, v in google_secret_manager_secret.secrets : startswith(v.secret_id, "taskorbit-")
    ])
    error_message = "All secrets must be prefixed with 'taskorbit-'."
  }
}

# ── Output map keys match the expected secret names ───────────────────────────

run "secret_ids_output_contains_expected_keys" {
  command = plan

  module {
    source = "./modules/secrets"
  }

  assert {
    condition     = contains(keys(module.secret_ids), "livekit-url")
    error_message = "secret_ids output must contain 'livekit-url'."
  }

  assert {
    condition     = contains(keys(module.secret_ids), "database-url")
    error_message = "secret_ids output must contain 'database-url'."
  }

  assert {
    condition     = contains(keys(module.secret_ids), "openai-api-key")
    error_message = "secret_ids output must contain 'openai-api-key'."
  }

  assert {
    condition     = contains(keys(module.secret_ids), "grafana-admin-password")
    error_message = "secret_ids output must contain 'grafana-admin-password'."
  }

  assert {
    condition     = contains(keys(module.secret_ids), "grafana-admin-user")
    error_message = "secret_ids output must contain 'grafana-admin-user'."
  }
}

# ── Secrets are labelled with managed-by = terraform ─────────────────────────

run "secrets_have_correct_labels" {
  command = plan

  module {
    source = "./modules/secrets"
  }

  assert {
    condition = alltrue([
      for k, v in google_secret_manager_secret.secrets : v.labels["managed-by"] == "terraform"
    ])
    error_message = "All secrets must have the 'managed-by = terraform' label."
  }

  assert {
    condition = alltrue([
      for k, v in google_secret_manager_secret.secrets : v.labels["app"] == "taskorbit"
    ])
    error_message = "All secrets must have the 'app = taskorbit' label."
  }
}
