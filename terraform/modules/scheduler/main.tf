# Auto-shutdown scheduler — reduces idle costs by stopping Cloud SQL and
# scaling down non-critical Cloud Run services outside business hours.
#
# Cloud Run frontend and backend already scale to 0 when idle (Cloud Run
# default behaviour). The worker stays at min_instances=1 to hold the
# LiveKit WebSocket open; it can be scaled to 0 here during off-hours.
#
# Cloud SQL does NOT scale automatically — it runs (and bills) 24/7 unless
# explicitly stopped. These jobs stop the instance at night and restart it
# each morning. Cron times are in Europe/Berlin (CET/CEST).

locals {
  sql_api_base = "https://sqladmin.googleapis.com/v1/projects/${var.project_id}/instances/${var.db_instance_name}"
  run_api_base = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/services"
}

# ── Service account for the scheduler ────────────────────────────────────────

resource "google_service_account" "scheduler" {
  account_id   = "taskorbit-scheduler"
  display_name = "TaskOrbit Cloud Scheduler"
  project      = var.project_id
}

resource "google_project_iam_member" "scheduler_sql_admin" {
  project = var.project_id
  role    = "roles/cloudsql.admin"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_project_iam_member" "scheduler_run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.scheduler.email}"
}

# ── Cloud SQL stop / start ────────────────────────────────────────────────────

resource "google_cloud_scheduler_job" "sql_stop" {
  count = var.enable_auto_shutdown ? 1 : 0

  name      = "taskorbit-sql-stop"
  region    = var.region
  project   = var.project_id
  schedule  = var.sql_stop_cron   # default: 22:00 Mon–Fri
  time_zone = var.time_zone

  http_target {
    uri         = local.sql_api_base
    http_method = "PATCH"

    # activationPolicy=NEVER stops the instance; billing for vCPU/RAM stops.
    body = base64encode(jsonencode({
      settings = { activationPolicy = "NEVER" }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 3
  }
}

resource "google_cloud_scheduler_job" "sql_start" {
  count = var.enable_auto_shutdown ? 1 : 0

  name      = "taskorbit-sql-start"
  region    = var.region
  project   = var.project_id
  schedule  = var.sql_start_cron  # default: 07:00 Mon–Fri
  time_zone = var.time_zone

  http_target {
    uri         = local.sql_api_base
    http_method = "PATCH"

    body = base64encode(jsonencode({
      settings = { activationPolicy = "ALWAYS" }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 3
  }
}

# ── Worker min-instance scale-down / scale-up ─────────────────────────────────
# The worker's min_instances=1 keeps the LiveKit agent alive during business
# hours. Scaling to 0 overnight saves Cloud Run idle costs but drops any
# active rooms — only enable if 24/7 availability is not required.

resource "google_cloud_scheduler_job" "worker_scale_down" {
  count = var.enable_auto_shutdown && var.scale_worker_overnight ? 1 : 0

  name      = "taskorbit-worker-scale-down"
  region    = var.region
  project   = var.project_id
  schedule  = var.sql_stop_cron
  time_zone = var.time_zone

  http_target {
    uri         = "${local.run_api_base}/taskorbit-worker"
    http_method = "PATCH"

    body = base64encode(jsonencode({
      template = { scaling = { minInstanceCount = 0 } }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 3
  }
}

resource "google_cloud_scheduler_job" "worker_scale_up" {
  count = var.enable_auto_shutdown && var.scale_worker_overnight ? 1 : 0

  name      = "taskorbit-worker-scale-up"
  region    = var.region
  project   = var.project_id
  schedule  = var.sql_start_cron
  time_zone = var.time_zone

  http_target {
    uri         = "${local.run_api_base}/taskorbit-worker"
    http_method = "PATCH"

    body = base64encode(jsonencode({
      template = { scaling = { minInstanceCount = 1 } }
    }))

    headers = {
      "Content-Type" = "application/json"
    }

    oauth_token {
      service_account_email = google_service_account.scheduler.email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }

  retry_config {
    retry_count = 3
  }
}
