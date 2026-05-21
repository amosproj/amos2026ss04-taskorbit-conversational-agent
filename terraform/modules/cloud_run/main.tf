locals {
  # Cloud SQL socket volume shared by backend and worker containers
  cloudsql_volume_name = "cloudsql"

  # CORS origins — fall back to the frontend domain if not explicitly set
  cors_origins = var.cors_allow_origins != "" ? var.cors_allow_origins : "https://${var.domain}"
}

# ── Backend (FastAPI API) ─────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "backend" {
  name     = "taskorbit-backend"
  location = var.region
  project  = var.project_id

  # Reachable from the load balancer and from within the VPC (Prometheus scrape)
  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = var.backend_sa_email

    scaling {
      min_instance_count = var.backend_min_instances
      max_instance_count = var.backend_max_instances
    }

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    volumes {
      name = local.cloudsql_volume_name
      cloud_sql_instance {
        instances = [var.cloud_sql_connection_name]
      }
    }

    containers {
      image = var.backend_image
      name  = "backend"

      ports {
        name           = "http1"
        container_port = 8000
      }

      env {
        name  = "APP_ENV"
        value = "production"
      }

      env {
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "LOG_JSON"
        value = "true"
      }

      env {
        name  = "API_HOST"
        value = "0.0.0.0"
      }

      env {
        name  = "API_PORT"
        value = "8000"
      }

      env {
        name  = "METRICS_ENABLED"
        value = "true"
      }

      env {
        name  = "OTEL_ENABLED"
        value = "false"
      }

      env {
        name  = "CORS_ALLOW_ORIGINS"
        value = local.cors_origins
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      # Secrets from Secret Manager
      dynamic "env" {
        for_each = {
          DATABASE_URL        = "database-url"
          LIVEKIT_URL         = "livekit-url"
          LIVEKIT_API_KEY     = "livekit-api-key"
          LIVEKIT_API_SECRET  = "livekit-api-secret"
          DEEPGRAM_API_KEY    = "deepgram-api-key"
          DEEPGRAM_MODEL      = "deepgram-model"
          DEEPGRAM_LANGUAGE   = "deepgram-language"
          ELEVENLABS_API_KEY  = "elevenlabs-api-key"
          ELEVENLABS_VOICE_ID = "elevenlabs-voice-id"
          ELEVENLABS_MODEL    = "elevenlabs-model"
          OPENAI_API_KEY      = "openai-api-key"
          OPENAI_MODEL        = "openai-model"
          GOOGLE_API_KEY      = "google-api-key"
          GOOGLE_MODEL        = "google-model"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = var.secret_ids[env.value]
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = local.cloudsql_volume_name
        mount_path = "/cloudsql"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        initial_delay_seconds = 15
        period_seconds        = 5
        failure_threshold     = 6
        timeout_seconds       = 3
      }

      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        period_seconds    = 15
        failure_threshold = 3
        timeout_seconds   = 3
      }
    }

    # Maximum request timeout — FastAPI streaming responses may be long
    timeout = "300s"
  }
}

# ── Worker (LiveKit agent) ────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "worker" {
  name     = "taskorbit-worker"
  location = var.region
  project  = var.project_id

  # Internal only — the worker connects OUT to LiveKit Cloud (no inbound public traffic).
  # Prometheus scrapes /metrics via the VPC connector.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = var.worker_sa_email

    scaling {
      # Keep at least one instance alive so the LiveKit agent is always listening.
      min_instance_count = var.worker_min_instances
      max_instance_count = var.worker_max_instances
    }

    vpc_access {
      connector = var.vpc_connector_id
      # Worker needs internet egress for LiveKit Cloud WebSocket + Deepgram + ElevenLabs
      egress = "ALL_TRAFFIC"
    }

    volumes {
      name = local.cloudsql_volume_name
      cloud_sql_instance {
        instances = [var.cloud_sql_connection_name]
      }
    }

    containers {
      image   = var.backend_image
      name    = "worker"
      # prod image has no poetry; taskorbit-worker is a venv entry-point on PATH
      command = ["taskorbit-worker", "dev"]

      ports {
        name           = "http1"
        container_port = 8001
      }

      env {
        name  = "APP_ENV"
        value = "production"
      }

      env {
        name  = "LOG_JSON"
        value = "true"
      }

      env {
        name  = "METRICS_ENABLED"
        value = "true"
      }

      env {
        name  = "PROMETHEUS_MULTIPROC_DIR"
        value = "/tmp/prometheus_multiproc"
      }

      env {
        name  = "PYTHONUNBUFFERED"
        value = "1"
      }

      env {
        name  = "PYTHONPATH"
        value = "/app/src"
      }

      dynamic "env" {
        for_each = {
          DATABASE_URL        = "database-url"
          LIVEKIT_URL         = "livekit-url"
          LIVEKIT_API_KEY     = "livekit-api-key"
          LIVEKIT_API_SECRET  = "livekit-api-secret"
          DEEPGRAM_API_KEY    = "deepgram-api-key"
          DEEPGRAM_MODEL      = "deepgram-model"
          DEEPGRAM_LANGUAGE   = "deepgram-language"
          ELEVENLABS_API_KEY  = "elevenlabs-api-key"
          ELEVENLABS_VOICE_ID = "elevenlabs-voice-id"
          ELEVENLABS_MODEL    = "elevenlabs-model"
          OPENAI_API_KEY      = "openai-api-key"
          OPENAI_MODEL        = "openai-model"
          GOOGLE_API_KEY      = "google-api-key"
          GOOGLE_MODEL        = "google-model"
        }
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = var.secret_ids[env.value]
              version = "latest"
            }
          }
        }
      }

      volume_mounts {
        name       = local.cloudsql_volume_name
        mount_path = "/cloudsql"
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "4Gi"
        }
      }

      startup_probe {
        http_get {
          path = "/metrics"
          port = 8001
        }
        initial_delay_seconds = 20
        period_seconds        = 10
        failure_threshold     = 6
        timeout_seconds       = 5
      }

      liveness_probe {
        http_get {
          path = "/metrics"
          port = 8001
        }
        period_seconds    = 30
        failure_threshold = 3
        timeout_seconds   = 5
      }
    }

    # Long timeout — worker maintains persistent LiveKit WebSocket sessions
    timeout = "3600s"
  }
}

# ── Frontend (React/Vite served via nginx) ────────────────────────────────────

resource "google_cloud_run_v2_service" "frontend" {
  name     = "taskorbit-frontend"
  location = var.region
  project  = var.project_id

  ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  template {
    service_account = var.frontend_sa_email

    scaling {
      min_instance_count = var.frontend_min_instances
      max_instance_count = var.frontend_max_instances
    }

    containers {
      image = var.frontend_image
      name  = "frontend"

      ports {
        name           = "http1"
        container_port = 80
      }

      env {
        name  = "VITE_API_URL"
        value = "https://api.${var.domain}"
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        http_get {
          path = "/"
          port = 80
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 3
      }
    }

    timeout = "60s"
  }
}

# ── Allow unauthenticated access (load balancer handles auth) ──────────────────

resource "google_cloud_run_v2_service_iam_member" "backend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "frontend_public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# ── Global HTTPS Load Balancer ────────────────────────────────────────────────

resource "google_compute_global_address" "lb_ip" {
  name    = "taskorbit-lb-ip"
  project = var.project_id
}

# Network Endpoint Groups (Serverless) — one per Cloud Run service
resource "google_compute_region_network_endpoint_group" "backend" {
  name                  = "taskorbit-backend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.backend.name
  }
}

resource "google_compute_region_network_endpoint_group" "frontend" {
  name                  = "taskorbit-frontend-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  cloud_run {
    service = google_cloud_run_v2_service.frontend.name
  }
}

# Backend services
resource "google_compute_backend_service" "backend" {
  name                  = "taskorbit-backend-bs"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.backend.id
  }

  log_config {
    enable      = true
    sample_rate = 0.1
  }
}

resource "google_compute_backend_service" "frontend" {
  name                  = "taskorbit-frontend-bs"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"

  backend {
    group = google_compute_region_network_endpoint_group.frontend.id
  }

  log_config {
    enable      = true
    sample_rate = 0.1
  }
}

# URL map — host-based routing
resource "google_compute_url_map" "main" {
  name            = "taskorbit-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.frontend.id

  host_rule {
    hosts        = ["api.${var.domain}"]
    path_matcher = "api"
  }

  host_rule {
    hosts        = [var.domain]
    path_matcher = "frontend"
  }

  path_matcher {
    name            = "api"
    default_service = google_compute_backend_service.backend.id
  }

  path_matcher {
    name            = "frontend"
    default_service = google_compute_backend_service.frontend.id
  }
}

# HTTP → HTTPS redirect map
resource "google_compute_url_map" "https_redirect" {
  name    = "taskorbit-https-redirect"
  project = var.project_id

  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

# Managed SSL certificates (one per domain)
resource "google_compute_managed_ssl_certificate" "main" {
  name    = "taskorbit-ssl"
  project = var.project_id

  managed {
    domains = [var.domain, "api.${var.domain}"]
  }
}

# HTTPS proxy
resource "google_compute_target_https_proxy" "main" {
  name             = "taskorbit-https-proxy"
  project          = var.project_id
  url_map          = google_compute_url_map.main.id
  ssl_certificates = [google_compute_managed_ssl_certificate.main.id]
}

# HTTP proxy (redirect only)
resource "google_compute_target_http_proxy" "redirect" {
  name    = "taskorbit-http-redirect-proxy"
  project = var.project_id
  url_map = google_compute_url_map.https_redirect.id
}

# Forwarding rules
resource "google_compute_global_forwarding_rule" "https" {
  name                  = "taskorbit-https"
  project               = var.project_id
  target                = google_compute_target_https_proxy.main.id
  ip_address            = google_compute_global_address.lb_ip.address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}

resource "google_compute_global_forwarding_rule" "http" {
  name                  = "taskorbit-http-redirect"
  project               = var.project_id
  target                = google_compute_target_http_proxy.redirect.id
  ip_address            = google_compute_global_address.lb_ip.address
  port_range            = "80"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
