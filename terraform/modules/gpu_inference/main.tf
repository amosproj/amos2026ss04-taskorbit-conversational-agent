# ── Service Account ───────────────────────────────────────────────────────────

resource "google_service_account" "ollama_sa" {
  count        = var.enable_gpu_inference ? 1 : 0
  account_id   = "taskorbit-ollama-sa"
  display_name = "TaskOrbit Ollama Inference SA"
  project      = var.project_id
}

resource "google_project_iam_member" "ollama_sa_roles" {
  for_each = var.enable_gpu_inference ? toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/secretmanager.secretAccessor",
  ]) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ollama_sa[0].email}"
}

# ── GCS bucket for persistent model storage ───────────────────────────────────
#
# IMPORTANT: Before first deploy, pre-populate the bucket with model weights:
#   1. Install Ollama locally
#   2. ollama pull gemma4:e4b && ollama pull gemma4:26b && ollama pull qwen3.6:27b
#   3. gsutil cp -r ~/.ollama/models gs://<project_id>-ollama-models/
#
# The Cloud Run container mounts this bucket at /models via GCSFuse.
# To add a new model later, copy weights to the bucket and update
# OLLAMA_MODEL in Cloud Run — no Terraform or code changes needed.

resource "google_storage_bucket" "ollama_models" {
  count    = var.enable_gpu_inference ? 1 : 0
  name     = "${var.project_id}-ollama-models"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true

  # Hierarchical namespace speeds up large LLM file access patterns
  hierarchical_namespace { enabled = true }
}

resource "google_storage_bucket_iam_member" "ollama_sa_gcs" {
  count  = var.enable_gpu_inference ? 1 : 0
  bucket = google_storage_bucket.ollama_models[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ollama_sa[0].email}"
}

# ── Cloud Run GPU service ──────────────────────────────────────────────────────

resource "google_cloud_run_v2_service" "ollama" {
  count    = var.enable_gpu_inference ? 1 : 0
  name     = "taskorbit-ollama-inference"
  location = var.region
  project  = var.project_id

  template {
    service_account = google_service_account.ollama_sa[0].email
    timeout         = "600s"
    max_instance_request_concurrency = 4

    # Deploy without GPU zonal redundancy. Redundant GPUs require a separate
    # quota (g.co/cloudrun/gpu-quota) that this project does not have, and they
    # cost more. Non-redundant GPUs are cheaper and sufficient for this workload.
    gpu_zonal_redundancy_disabled = true

    containers {
      image = "ollama/ollama:${var.ollama_version}"

      ports {
        container_port = 8080
      }

      env {
        name  = "OLLAMA_HOST"
        value = "0.0.0.0:8080"
      }
      env {
        # Keep model loaded in VRAM indefinitely — avoids re-load latency between requests
        name  = "OLLAMA_KEEP_ALIVE"
        value = "-1"
      }
      env {
        name  = "OLLAMA_MODELS"
        value = "/models"
      }
      env {
        name  = "OLLAMA_DEBUG"
        value = "false"
      }
      env {
        name  = "OLLAMA_NUM_PARALLEL"
        value = "4"
      }
      env {
        # Override Ollama's default 4K context window. 32K is a safe baseline
        # for most tasks; increase per-request for long-context workloads.
        name  = "OLLAMA_NUM_CTX"
        value = "32768"
      }

      resources {
        limits = {
          cpu              = "8"
          memory           = "32Gi"
          "nvidia.com/gpu" = "1"
        }
        startup_cpu_boost = true
      }

      volume_mounts {
        name       = "models"
        mount_path = "/models"
      }

      # GPU containers take 60-120s to initialise — generous startup probe
      startup_probe {
        tcp_socket {
          port = 8080
        }
        initial_delay_seconds = 60
        failure_threshold     = 5
        period_seconds        = 30
        timeout_seconds       = 10
      }

      liveness_probe {
        http_get {
          path = "/api/tags"
          port = 8080
        }
        period_seconds    = 60
        failure_threshold = 3
        timeout_seconds   = 10
      }
    }

    volumes {
      name = "models"
      gcs {
        bucket    = google_storage_bucket.ollama_models[0].name
        read_only = false
      }
    }

    annotations = {
      # Explicitly disable zonal redundancy — required when the project does not
      # have GPU zonal-redundancy quota. Without this, Cloud Run requires
      # max_instance_count >= 2 AND the matching quota, which most projects lack.
      "run.googleapis.com/gpu-zonal-redundancy-disabled" = "true"
    }

    scaling {
      # 0 = scale to zero (cheapest); set to 1 during active development
      # to avoid 60-120s cold start penalty on every request
      min_instance_count = var.min_instances
      max_instance_count = 1
    }

    node_selector {
      # Request NVIDIA L4 GPU — most cost-efficient GPU available on Cloud Run
      accelerator = "nvidia-l4"
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# ── IAM: only the backend SA can invoke the Ollama service ────────────────────
#
# --no-allow-unauthenticated is the Cloud Run default.
# The backend OllamaClient fetches a GCP identity token per request.

resource "google_cloud_run_v2_service_iam_member" "backend_invoker" {
  count    = var.enable_gpu_inference ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.ollama[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}
