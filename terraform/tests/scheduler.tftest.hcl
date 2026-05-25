# Tests for modules/scheduler
#
# Verifies the count logic that controls whether Cloud Scheduler jobs are
# created based on enable_auto_shutdown and scale_worker_overnight flags.
# Uses mock_provider so no real GCP credentials or project are required.

mock_provider "google" {}

# ── Shared variables ──────────────────────────────────────────────────────────

variables {
  project_id       = "test-project"
  region           = "europe-west1"
  db_instance_name = "taskorbit-postgres"
}

# ── auto_shutdown disabled ────────────────────────────────────────────────────

run "no_jobs_when_auto_shutdown_disabled" {
  command = plan

  module {
    source = "./modules/scheduler"
  }

  variables {
    enable_auto_shutdown   = false
    scale_worker_overnight = false
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_stop) == 0
    error_message = "Expected no sql_stop job when auto_shutdown is disabled."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_start) == 0
    error_message = "Expected no sql_start job when auto_shutdown is disabled."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_down) == 0
    error_message = "Expected no worker_scale_down job when auto_shutdown is disabled."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_up) == 0
    error_message = "Expected no worker_scale_up job when auto_shutdown is disabled."
  }
}

# ── auto_shutdown enabled, worker scale-down disabled ─────────────────────────

run "sql_jobs_only_when_worker_overnight_disabled" {
  command = plan

  module {
    source = "./modules/scheduler"
  }

  variables {
    enable_auto_shutdown   = true
    scale_worker_overnight = false
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_stop) == 1
    error_message = "Expected exactly one sql_stop job."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_start) == 1
    error_message = "Expected exactly one sql_start job."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_down) == 0
    error_message = "Expected no worker_scale_down job when scale_worker_overnight is false."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_up) == 0
    error_message = "Expected no worker_scale_up job when scale_worker_overnight is false."
  }
}

# ── auto_shutdown enabled, worker scale-down enabled ─────────────────────────

run "all_four_jobs_when_both_flags_enabled" {
  command = plan

  module {
    source = "./modules/scheduler"
  }

  variables {
    enable_auto_shutdown   = true
    scale_worker_overnight = true
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_stop) == 1
    error_message = "Expected exactly one sql_stop job."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.sql_start) == 1
    error_message = "Expected exactly one sql_start job."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_down) == 1
    error_message = "Expected exactly one worker_scale_down job."
  }

  assert {
    condition     = length(google_cloud_scheduler_job.worker_scale_up) == 1
    error_message = "Expected exactly one worker_scale_up job."
  }
}

# ── Cron schedule values ──────────────────────────────────────────────────────

run "default_cron_schedules_are_correct" {
  command = plan

  module {
    source = "./modules/scheduler"
  }

  variables {
    enable_auto_shutdown   = true
    scale_worker_overnight = false
  }

  assert {
    condition     = google_cloud_scheduler_job.sql_stop[0].schedule == "0 22 * * 1-5"
    error_message = "sql_stop schedule should be 22:00 Mon-Fri."
  }

  assert {
    condition     = google_cloud_scheduler_job.sql_start[0].schedule == "0 7 * * 1-5"
    error_message = "sql_start schedule should be 07:00 Mon-Fri."
  }

  assert {
    condition     = google_cloud_scheduler_job.sql_stop[0].time_zone == "Europe/Berlin"
    error_message = "time_zone should default to Europe/Berlin."
  }
}
