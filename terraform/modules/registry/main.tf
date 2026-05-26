resource "google_artifact_registry_repository" "docker" {
  repository_id = "taskorbit"
  format        = "DOCKER"
  location      = var.region
  project       = var.project_id
  description   = "TaskOrbit container images (backend, worker, frontend)"

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "keep-tagged-releases"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }

  cleanup_policies {
    id     = "delete-old-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s" # 7 days
    }
  }
}
