# Tests for modules/observability
#
# Verifies that Loki, Prometheus and Grafana Cloud Run services are created
# with the correct ingress settings, that GCS buckets use the expected naming
# convention, and that the Pub/Sub push subscription is wired to Loki.
# Uses mock_provider so no real GCP credentials are required.

mock_provider "google" {}

variables {
  project_id             = "test-project"
  region                 = "europe-west1"
  domain                 = "taskorbit.example.com"
  backend_sa_email       = "taskorbit-backend@test-project.iam.gserviceaccount.com"
  worker_sa_email        = "taskorbit-worker@test-project.iam.gserviceaccount.com"
  observability_sa_email = "taskorbit-observability@test-project.iam.gserviceaccount.com"
  backend_url            = "https://taskorbit-backend-abc123.a.run.app"
  worker_url             = "https://taskorbit-worker-abc123.a.run.app"

  secret_ids = {
    "grafana-admin-password" = "taskorbit-grafana-admin-password"
  }
}

# ── Ingress settings ──────────────────────────────────────────────────────────

run "loki_and_prometheus_are_internal_only" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = google_cloud_run_v2_service.loki.ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "Loki must not be exposed publicly — only Grafana and the Pub/Sub subscription reach it."
  }

  assert {
    condition     = google_cloud_run_v2_service.prometheus.ingress == "INGRESS_TRAFFIC_INTERNAL_ONLY"
    error_message = "Prometheus must not be exposed publicly — only Grafana scrapes it."
  }
}

run "grafana_uses_internal_load_balancer" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = google_cloud_run_v2_service.grafana.ingress == "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    error_message = "Grafana must be reachable only via the internal load balancer, not directly."
  }
}

# ── GCS bucket naming ─────────────────────────────────────────────────────────

run "gcs_buckets_use_project_prefix" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = google_storage_bucket.loki.name == "test-project-taskorbit-loki"
    error_message = "Loki GCS bucket must be named <project_id>-taskorbit-loki."
  }

  assert {
    condition     = google_storage_bucket.prometheus.name == "test-project-taskorbit-prometheus"
    error_message = "Prometheus GCS bucket must be named <project_id>-taskorbit-prometheus."
  }
}

# ── GCS bucket retention ──────────────────────────────────────────────────────

run "gcs_buckets_have_correct_retention" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = google_storage_bucket.loki.lifecycle_rule[0].condition[0].age == 90
    error_message = "Loki bucket must retain logs for 90 days."
  }

  assert {
    condition     = google_storage_bucket.prometheus.lifecycle_rule[0].condition[0].age == 30
    error_message = "Prometheus bucket must retain metrics for 30 days."
  }
}

# ── Pub/Sub log pipeline ──────────────────────────────────────────────────────

run "pubsub_subscription_exists_for_loki" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = google_pubsub_subscription.loki_push.name == "taskorbit-loki-push"
    error_message = "Pub/Sub push subscription must be named taskorbit-loki-push."
  }

  assert {
    condition     = google_pubsub_subscription.loki_push.topic == google_pubsub_topic.loki_logs.id
    error_message = "Push subscription must be attached to the taskorbit-loki-logs topic."
  }
}

# ── Grafana SSL certificate ───────────────────────────────────────────────────

run "grafana_ssl_cert_covers_grafana_subdomain" {
  command = plan

  module {
    source = "./modules/observability"
  }

  assert {
    condition     = contains(google_compute_managed_ssl_certificate.grafana.managed[0].domains, "grafana.taskorbit.example.com")
    error_message = "Grafana SSL certificate must cover grafana.<domain>."
  }
}
