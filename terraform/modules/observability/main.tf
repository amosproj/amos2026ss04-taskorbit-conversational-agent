locals {
  # Strip the https:// prefix for Prometheus target hostnames
  backend_host = replace(var.backend_url, "https://", "")
  worker_host  = replace(var.worker_url, "https://", "")

  prometheus_config = <<-YAML
    global:
      scrape_interval: 5s
      evaluation_interval: 5s

    scrape_configs:
      - job_name: taskorbit-backend
        metrics_path: /metrics
        scheme: https
        # Cloud Run requires a valid OIDC token; Prometheus uses the SA attached
        # to its Cloud Run instance via the metadata server.
        authorization:
          type: Bearer
          credentials_file: /var/run/secrets/google/token
        static_configs:
          - targets:
              - ${local.backend_host}
        relabel_configs:
          - target_label: job
            replacement: taskorbit-backend

      - job_name: taskorbit-worker
        metrics_path: /metrics
        scheme: https
        authorization:
          type: Bearer
          credentials_file: /var/run/secrets/google/token
        static_configs:
          - targets:
              - ${local.worker_host}
        relabel_configs:
          - target_label: job
            replacement: taskorbit-worker
  YAML

  loki_config = <<-YAML
    auth_enabled: false

    server:
      http_listen_port: 3100
      grpc_listen_port: 9095

    common:
      instance_addr: 127.0.0.1
      path_prefix: /loki
      storage:
        gcs:
          bucket_name: ${google_storage_bucket.loki.name}
      replication_factor: 1
      ring:
        kvstore:
          store: inmemory

    schema_config:
      configs:
        - from: "2024-01-01"
          store: tsdb
          object_store: gcs
          schema: v13
          index:
            prefix: loki_index_
            period: 24h

    ruler:
      alertmanager_url: http://localhost:9093

    analytics:
      reporting_enabled: false
  YAML
}

# ── GCS buckets ───────────────────────────────────────────────────────────────

resource "google_storage_bucket" "loki" {
  name          = "${var.project_id}-taskorbit-loki"
  location      = var.region
  project       = var.project_id
  force_destroy = false

  uniform_bucket_level_access = true

  versioning {
    enabled = false
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

resource "google_storage_bucket" "prometheus" {
  name          = "${var.project_id}-taskorbit-prometheus"
  location      = var.region
  project       = var.project_id
  force_destroy = false

  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }
}

# IAM: observability SA owns both buckets
resource "google_storage_bucket_iam_member" "loki_observability" {
  bucket = google_storage_bucket.loki.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.observability_sa_email}"
}

resource "google_storage_bucket_iam_member" "prometheus_observability" {
  bucket = google_storage_bucket.prometheus.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.observability_sa_email}"
}

# ── Config secrets ────────────────────────────────────────────────────────────

resource "google_secret_manager_secret" "prometheus_config" {
  secret_id = "taskorbit-prometheus-config"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    managed-by = "terraform"
    app        = "taskorbit"
    component  = "prometheus"
  }
}

resource "google_secret_manager_secret_version" "prometheus_config" {
  secret      = google_secret_manager_secret.prometheus_config.id
  secret_data = local.prometheus_config
}

resource "google_secret_manager_secret" "loki_config" {
  secret_id = "taskorbit-loki-config"
  project   = var.project_id

  replication {
    auto {}
  }

  labels = {
    managed-by = "terraform"
    app        = "taskorbit"
    component  = "loki"
  }
}

resource "google_secret_manager_secret_version" "loki_config" {
  secret      = google_secret_manager_secret.loki_config.id
  secret_data = local.loki_config
}

# Grant observability SA access to its own config secrets
resource "google_secret_manager_secret_iam_member" "prometheus_config_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.prometheus_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.observability_sa_email}"
}

resource "google_secret_manager_secret_iam_member" "loki_config_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.loki_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.observability_sa_email}"
}

resource "google_secret_manager_secret_iam_member" "grafana_password_accessor" {
  project   = var.project_id
  secret_id = var.secret_ids["grafana-admin-password"]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.observability_sa_email}"
}

# ── Loki Cloud Run service ─────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "loki" {
  name     = "taskorbit-loki"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.observability_sa_email

    scaling {
      min_instance_count = 1
      max_instance_count = 2
    }

    volumes {
      name = "loki-config"
      secret {
        secret = google_secret_manager_secret.loki_config.secret_id
        items {
          version = "latest"
          path    = "loki.yaml"
          mode    = 0444
        }
      }
    }

    containers {
      image = "grafana/loki:3.2.0"
      name  = "loki"

      args = ["-config.file=/etc/loki/loki.yaml"]

      ports {
        name           = "http1"
        container_port = 3100
      }

      volume_mounts {
        name       = "loki-config"
        mount_path = "/etc/loki"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/ready"
          port = 3100
        }
        initial_delay_seconds = 15
        period_seconds        = 10
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/ready"
          port = 3100
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    timeout = "300s"
  }

  depends_on = [
    google_secret_manager_secret_version.loki_config,
    google_storage_bucket_iam_member.loki_observability,
  ]
}

# ── Prometheus Cloud Run service ───────────────────────────────────────────────

resource "google_cloud_run_v2_service" "prometheus" {
  name     = "taskorbit-prometheus"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.observability_sa_email

    scaling {
      min_instance_count = 1
      max_instance_count = 1
    }

    volumes {
      name = "prometheus-config"
      secret {
        secret = google_secret_manager_secret.prometheus_config.secret_id
        items {
          version = "latest"
          path    = "prometheus.yml"
          mode    = 0444
        }
      }
    }

    containers {
      image = "prom/prometheus:v2.55.0"
      name  = "prometheus"

      args = [
        "--config.file=/etc/prometheus/prometheus.yml",
        "--storage.tsdb.path=/prometheus",
        "--storage.tsdb.retention.time=15d",
        "--web.enable-lifecycle",
        "--web.enable-admin-api",
      ]

      ports {
        name           = "http1"
        container_port = 9090
      }

      volume_mounts {
        name       = "prometheus-config"
        mount_path = "/etc/prometheus"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "2Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/-/healthy"
          port = 9090
        }
        initial_delay_seconds = 10
        period_seconds        = 10
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/-/healthy"
          port = 9090
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    timeout = "300s"
  }

  depends_on = [google_secret_manager_secret_version.prometheus_config]
}

# ── Grafana Cloud Run service ──────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "grafana" {
  name     = "taskorbit-grafana"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = var.observability_sa_email

    scaling {
      min_instance_count = 1
      max_instance_count = 2
    }

    containers {
      image = "grafana/grafana:11.3.0"
      name  = "grafana"

      ports {
        name           = "http1"
        container_port = 3000
      }

      env {
        name  = "GF_SERVER_ROOT_URL"
        value = "https://grafana.${var.domain}"
      }

      # Production: anonymous admin disabled — use admin credentials
      env {
        name  = "GF_AUTH_ANONYMOUS_ENABLED"
        value = "false"
      }

      env {
        name  = "GF_AUTH_DISABLE_LOGIN_FORM"
        value = "false"
      }

      env {
        name = "GF_SECURITY_ADMIN_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids["grafana-admin-password"]
            version = "latest"
          }
        }
      }

      env {
        name  = "GF_ANALYTICS_REPORTING_ENABLED"
        value = "false"
      }

      env {
        name  = "GF_LOG_LEVEL"
        value = "warn"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        http_get {
          path = "/api/health"
          port = 3000
        }
        initial_delay_seconds = 15
        period_seconds        = 10
        failure_threshold     = 6
      }

      liveness_probe {
        http_get {
          path = "/api/health"
          port = 3000
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    timeout = "60s"
  }
}

# Allow unauthenticated access to Grafana (login form handles auth)
resource "google_cloud_run_v2_service_iam_member" "grafana_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.grafana.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Grafana load balancer (grafana.<domain>) ───────────────────────────────────

resource "google_compute_region_network_endpoint_group" "grafana" {
  name                  = "taskorbit-grafana-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.grafana.name
  }
}

resource "google_compute_backend_service" "grafana" {
  name                  = "taskorbit-grafana-bs"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.grafana.id
  }
}

resource "google_compute_managed_ssl_certificate" "grafana" {
  name    = "taskorbit-grafana-ssl"
  project = var.project_id

  managed {
    domains = ["grafana.${var.domain}"]
  }
}

resource "google_compute_url_map" "grafana" {
  name            = "taskorbit-grafana-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.grafana.id
}

resource "google_compute_target_https_proxy" "grafana" {
  name             = "taskorbit-grafana-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.grafana.id
  ssl_certificates = [google_compute_managed_ssl_certificate.grafana.id]
}

resource "google_compute_global_address" "grafana_lb_ip" {
  name    = "taskorbit-grafana-lb-ip"
  project = var.project_id
}

resource "google_compute_global_forwarding_rule" "grafana_https" {
  name                  = "taskorbit-grafana-https"
  project               = var.project_id
  target                = google_compute_target_https_proxy.grafana.id
  ip_address            = google_compute_global_address.grafana_lb_ip.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

# ── Cloud Logging sink → Pub/Sub → Loki (log routing) ─────────────────────────

resource "google_pubsub_topic" "loki_logs" {
  name    = "taskorbit-loki-logs"
  project = var.project_id

  message_retention_duration = "86400s" # 24 h
}

# Log sink: forward all taskorbit Cloud Run logs to Pub/Sub
resource "google_logging_project_sink" "loki" {
  name        = "taskorbit-loki-sink"
  project     = var.project_id
  destination = "pubsub.googleapis.com/${google_pubsub_topic.loki_logs.id}"

  filter = <<-FILTER
    resource.type="cloud_run_revision"
    resource.labels.service_name=("taskorbit-backend" OR "taskorbit-worker")
  FILTER

  unique_writer_identity = true
}

# Grant the sink's service account permission to publish to the topic
resource "google_pubsub_topic_iam_member" "sink_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.loki_logs.name
  role    = "roles/pubsub.publisher"
  member  = google_logging_project_sink.loki.writer_identity
}
