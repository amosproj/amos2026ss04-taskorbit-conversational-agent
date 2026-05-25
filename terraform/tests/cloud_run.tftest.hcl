# Tests for modules/cloud_run
#
# Verifies ingress settings, CORS origin wiring, SSL certificate domains,
# and that the frontend BACKEND_URL env var is set.
# Uses mock_provider so no real GCP credentials are required.

mock_provider "google" {}

variables {
  project_id    = "test-project"
  region        = "europe-west1"
  domain        = "taskorbit.example.com"
  backend_image  = "europe-west1-docker.pkg.dev/test-project/taskorbit/backend:latest"
  frontend_image = "europe-west1-docker.pkg.dev/test-project/taskorbit/frontend:latest"

  backend_sa_email  = "taskorbit-backend@test-project.iam.gserviceaccount.com"
  worker_sa_email   = "taskorbit-worker@test-project.iam.gserviceaccount.com"
  frontend_sa_email = "taskorbit-frontend@test-project.iam.gserviceaccount.com"

  vpc_connector_id          = "projects/test-project/locations/europe-west1/connectors/taskorbit-connector"
  cloud_sql_connection_name = "test-project:europe-west1:taskorbit-postgres"

  secret_ids = {
    "database-url"        = "taskorbit-database-url"
    "livekit-url"         = "taskorbit-livekit-url"
    "livekit-api-key"     = "taskorbit-livekit-api-key"
    "livekit-api-secret"  = "taskorbit-livekit-api-secret"
    "deepgram-api-key"    = "taskorbit-deepgram-api-key"
    "deepgram-model"      = "taskorbit-deepgram-model"
    "deepgram-language"   = "taskorbit-deepgram-language"
    "elevenlabs-api-key"  = "taskorbit-elevenlabs-api-key"
    "elevenlabs-voice-id" = "taskorbit-elevenlabs-voice-id"
    "elevenlabs-model"    = "taskorbit-elevenlabs-model"
    "openai-api-key"      = "taskorbit-openai-api-key"
    "openai-model"        = "taskorbit-openai-model"
    "google-api-key"      = "taskorbit-google-api-key"
    "google-model"        = "taskorbit-google-model"
  }
}

# ── Ingress settings ──────────────────────────────────────────────────────────

run "worker_is_internal_only" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  assert {
    condition     = google_cloud_run_v2_service.worker.ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "Worker must only accept internal traffic — it connects out to LiveKit, not inbound."
  }
}

run "backend_and_frontend_accept_all_traffic" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  assert {
    condition     = google_cloud_run_v2_service.backend.ingress == "INGRESS_TRAFFIC_ALL"
    error_message = "Backend ingress must be INGRESS_TRAFFIC_ALL until LB + domain are confirmed."
  }

  assert {
    condition     = google_cloud_run_v2_service.frontend.ingress == "INGRESS_TRAFFIC_ALL"
    error_message = "Frontend ingress must be INGRESS_TRAFFIC_ALL until LB + domain are confirmed."
  }
}

# ── CORS origin wiring ────────────────────────────────────────────────────────

run "cors_defaults_to_domain_when_not_set" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  variables {
    cors_allow_origins = ""
  }

  assert {
    condition = anytrue([
      for e in google_cloud_run_v2_service.backend.template[0].containers[0].env :
      e.name == "CORS_ALLOW_ORIGINS" && e.value == "https://taskorbit.example.com"
    ])
    error_message = "CORS_ALLOW_ORIGINS must default to https://<domain> when cors_allow_origins is empty."
  }
}

run "cors_uses_explicit_override" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  variables {
    cors_allow_origins = "https://taskorbit-frontend-abc123.a.run.app"
  }

  assert {
    condition = anytrue([
      for e in google_cloud_run_v2_service.backend.template[0].containers[0].env :
      e.name == "CORS_ALLOW_ORIGINS" && e.value == "https://taskorbit-frontend-abc123.a.run.app"
    ])
    error_message = "CORS_ALLOW_ORIGINS must use the explicit cors_allow_origins value when set."
  }
}

# ── SSL certificate domains ───────────────────────────────────────────────────

run "ssl_cert_covers_domain_and_api_subdomain" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  assert {
    condition     = contains(google_compute_managed_ssl_certificate.main.managed[0].domains, "taskorbit.example.com")
    error_message = "SSL certificate must cover the root domain."
  }

  assert {
    condition     = contains(google_compute_managed_ssl_certificate.main.managed[0].domains, "api.taskorbit.example.com")
    error_message = "SSL certificate must cover the api. subdomain."
  }
}

# ── Frontend BACKEND_URL env var ──────────────────────────────────────────────

run "frontend_has_backend_url_env" {
  command = plan

  module {
    source = "./modules/cloud_run"
  }

  assert {
    condition = anytrue([
      for e in google_cloud_run_v2_service.frontend.template[0].containers[0].env :
      e.name == "BACKEND_URL"
    ])
    error_message = "Frontend container must have BACKEND_URL set so nginx can proxy /api/* to the backend."
  }
}
