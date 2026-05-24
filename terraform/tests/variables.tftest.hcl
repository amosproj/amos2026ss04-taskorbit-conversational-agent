# Tests for root module variable validations
#
# Verifies that invalid inputs are rejected at plan time with the correct
# error messages. Uses expect_failures to assert that a validation fires.
# Valid baseline values are declared in the shared variables block and
# overridden per run.

mock_provider "google" {}
mock_provider "google-beta" {}
mock_provider "random" {}

# Baseline: a valid set of values that all validations accept.
variables {
  project_id             = "my-gcp-project"
  region                 = "europe-west1"
  domain                 = "taskorbit.example.com"
  github_repository      = "amosproj/amos2026ss04-taskorbit-conversational-agent"
  backend_image          = "europe-west1-docker.pkg.dev/my-project/taskorbit/backend:latest"
  frontend_image         = "europe-west1-docker.pkg.dev/my-project/taskorbit/frontend:latest"
  livekit_url            = "wss://test.livekit.cloud"
  livekit_api_key        = "test-api-key"
  livekit_api_secret     = "test-api-secret"
  deepgram_api_key       = "test-deepgram-key"
  elevenlabs_api_key     = "test-elevenlabs-key"
  openai_api_key         = ""
  google_api_key         = ""
  grafana_admin_password = "strongpassword123"
}

# ── project_id ────────────────────────────────────────────────────────────────

run "rejects_empty_project_id" {
  command = plan

  variables {
    project_id = ""
  }

  expect_failures = [var.project_id]
}

# ── region ────────────────────────────────────────────────────────────────────

run "rejects_invalid_region_format" {
  command = plan

  variables {
    region = "europe_west1"  # underscore instead of hyphen
  }

  expect_failures = [var.region]
}

# ── domain ────────────────────────────────────────────────────────────────────

run "rejects_bare_domain_without_tld" {
  command = plan

  variables {
    domain = "notadomain"
  }

  expect_failures = [var.domain]
}

# ── github_repository ─────────────────────────────────────────────────────────

run "rejects_github_repository_without_slash" {
  command = plan

  variables {
    github_repository = "justaname"
  }

  expect_failures = [var.github_repository]
}

# ── backend_image ─────────────────────────────────────────────────────────────

run "rejects_backend_image_without_tag" {
  command = plan

  variables {
    backend_image = "europe-west1-docker.pkg.dev/my-project/taskorbit/backend"
  }

  expect_failures = [var.backend_image]
}

# ── livekit_url ───────────────────────────────────────────────────────────────

run "rejects_livekit_url_with_https_scheme" {
  command = plan

  variables {
    livekit_url = "https://test.livekit.cloud"
  }

  expect_failures = [var.livekit_url]
}

run "rejects_livekit_url_without_scheme" {
  command = plan

  variables {
    livekit_url = "test.livekit.cloud"
  }

  expect_failures = [var.livekit_url]
}

# ── deepgram_api_key ──────────────────────────────────────────────────────────

run "rejects_empty_deepgram_api_key" {
  command = plan

  variables {
    deepgram_api_key = ""
  }

  expect_failures = [var.deepgram_api_key]
}

# ── elevenlabs_api_key ────────────────────────────────────────────────────────

run "rejects_empty_elevenlabs_api_key" {
  command = plan

  variables {
    elevenlabs_api_key = ""
  }

  expect_failures = [var.elevenlabs_api_key]
}

# ── livekit_api_key / livekit_api_secret ──────────────────────────────────────

run "rejects_empty_livekit_api_key" {
  command = plan

  variables {
    livekit_api_key = ""
  }

  expect_failures = [var.livekit_api_key]
}

run "rejects_empty_livekit_api_secret" {
  command = plan

  variables {
    livekit_api_secret = ""
  }

  expect_failures = [var.livekit_api_secret]
}

# ── grafana_admin_password ────────────────────────────────────────────────────

run "rejects_short_grafana_password" {
  command = plan

  variables {
    grafana_admin_password = "tooshort"  # 8 chars, minimum is 12
  }

  expect_failures = [var.grafana_admin_password]
}

# ── scaling: min > max ────────────────────────────────────────────────────────

run "rejects_backend_min_greater_than_max" {
  command = plan

  variables {
    backend_min_instances = 5
    backend_max_instances = 2
  }

  expect_failures = [var.backend_min_instances]
}
