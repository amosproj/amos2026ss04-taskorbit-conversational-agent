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

resource "google_project_iam_member" "backend_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_project_iam_member" "backend_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# ── Worker IAM bindings ───────────────────────────────────────────────────────

resource "google_project_iam_member" "worker_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

resource "google_project_iam_member" "worker_cloudsql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# Worker needs GCS write access for prometheus multiprocess dir
resource "google_project_iam_member" "worker_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.worker.email}"
}

# ── Observability IAM bindings ────────────────────────────────────────────────

resource "google_project_iam_member" "observability_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.observability.email}"
}

resource "google_project_iam_member" "observability_storage_object_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.observability.email}"
}

# Prometheus needs to invoke backend/worker Cloud Run to scrape /metrics
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

resource "google_project_iam_member" "cicd_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.cicd.email}"
}

# terraform-deployer SA transitional bindings — remove after switching
# GitHub Actions to taskorbit-cicd SA key (see CLAUDE.md).
resource "google_project_iam_member" "deployer_artifact_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:terraform-deployer@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_project_iam_member" "deployer_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:terraform-deployer@${var.project_id}.iam.gserviceaccount.com"
}

# terraform-deployer must be able to actAs each Cloud Run service account
# when deploying services (iam.serviceaccounts.actAs required by Cloud Run).
resource "google_service_account_iam_member" "deployer_actAs_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:terraform-deployer@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "deployer_actAs_worker" {
  service_account_id = google_service_account.worker.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:terraform-deployer@${var.project_id}.iam.gserviceaccount.com"
}

resource "google_service_account_iam_member" "deployer_actAs_frontend" {
  service_account_id = google_service_account.frontend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:terraform-deployer@${var.project_id}.iam.gserviceaccount.com"
}

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
