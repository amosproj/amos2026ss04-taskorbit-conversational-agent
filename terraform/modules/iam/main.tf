locals {
  # Secrets needed by the backend and worker (excludes grafana credentials).
  app_secret_keys = [
    "livekit-url", "livekit-api-key", "livekit-api-secret",
    "deepgram-api-key", "deepgram-model", "deepgram-language",
    "elevenlabs-api-key", "elevenlabs-voice-id", "elevenlabs-model",
    "openai-api-key", "openai-model",
    "google-api-key", "google-model",
    "openrouter-api-key", "openrouter-model",
    "database-url",
  ]
  # Secrets needed only by the observability stack.
  grafana_secret_keys = ["grafana-admin-user", "grafana-admin-password"]
}

# ── Service accounts ──────────────────────────────────────────────────────────

resource "google_service_account" "backend" {
  account_id   = "taskorbit-backend"
  display_name = "TaskOrbit Backend API"
  project      = var.project_id
}

resource "google_service_account" "worker" {
  account_id   = "taskorbit-worker"
  display_name = "TaskOrbit LiveKit Worker"
  project      = var.project_id
}

resource "google_service_account" "frontend" {
  account_id   = "taskorbit-frontend"
  display_name = "TaskOrbit Frontend"
  project      = var.project_id
}

resource "google_service_account" "observability" {
  account_id   = "taskorbit-observability"
  display_name = "TaskOrbit Observability (Prometheus/Loki/Grafana)"
  project      = var.project_id
}

# CI/CD service account — used by GitHub Actions for image push + Cloud Run deploy
resource "google_service_account" "cicd" {
  account_id   = "taskorbit-cicd"
  display_name = "TaskOrbit CI/CD (GitHub Actions)"
  project      = var.project_id
}

# ── Backend IAM bindings ──────────────────────────────────────────────────────

# Resource-scoped: backend can only read the secrets it actually mounts.
resource "google_secret_manager_secret_iam_member" "backend_secret_accessor" {
  for_each  = toset(local.app_secret_keys)
  project   = var.project_id
  secret_id = var.secret_ids[each.key]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# ── Worker IAM bindings ───────────────────────────────────────────────────────

# Resource-scoped: worker can only read the secrets it actually mounts.
resource "google_secret_manager_secret_iam_member" "worker_secret_accessor" {
  for_each  = toset(local.app_secret_keys)
  project   = var.project_id
  secret_id = var.secret_ids[each.key]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# ── Observability IAM bindings ────────────────────────────────────────────────

# Resource-scoped: observability SA only reads Grafana credentials.
resource "google_secret_manager_secret_iam_member" "observability_secret_accessor" {
  for_each  = toset(local.grafana_secret_keys)
  project   = var.project_id
  secret_id = var.secret_ids[each.key]
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.observability.email}"
}

resource "google_project_iam_member" "observability_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.observability.email}"
}

# Prometheus invokes backend/worker Cloud Run services to scrape /metrics.
resource "google_project_iam_member" "observability_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.observability.email}"
}

# ── CI/CD IAM bindings ────────────────────────────────────────────────────────

resource "google_project_iam_member" "cicd_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_sa_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

# ── Terraform deployer bindings (cicd SA used for terraform plan/apply) ───────

resource "google_project_iam_member" "cicd_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_secret_admin" {
  project = var.project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_sql_admin" {
  project = var.project_id
  role    = "roles/cloudsql.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_network_admin" {
  project = var.project_id
  role    = "roles/compute.networkAdmin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_security_admin" {
  project = var.project_id
  role    = "roles/iam.securityAdmin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_pubsub_admin" {
  project = var.project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_logging_admin" {
  project = var.project_id
  role    = "roles/logging.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_scheduler_admin" {
  project = var.project_id
  role    = "roles/cloudscheduler.admin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

resource "google_project_iam_member" "cicd_service_usage" {
  project = var.project_id
  role    = "roles/serviceusage.serviceUsageAdmin"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

# cicd SA does not need secretAccessor — it deploys images, not secret values.

# ── Workload Identity (GitHub Actions OIDC — no long-lived key) ───────────────

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
  project                   = var.project_id
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  project                            = var.project_id
  display_name                       = "GitHub Actions OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  # Restrict to this repository only — prevents other repos from impersonating the CI/CD SA
  attribute_condition = "assertion.repository == '${var.github_repository}'"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "cicd_workload_identity" {
  service_account_id = google_service_account.cicd.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}
