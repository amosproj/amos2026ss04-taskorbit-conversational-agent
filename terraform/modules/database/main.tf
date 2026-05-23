resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_database_instance" "main" {
  name             = "taskorbit-postgres"
  database_version = "POSTGRES_16"
  region           = var.region
  project          = var.project_id

  # Prevents accidental deletion via `terraform destroy`
  deletion_protection = true

  settings {
    # Shared-core tier — cheapest option, suitable for dev/free tier
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL" # single zone — no HA on shared-core

    ip_configuration {
      ipv4_enabled                                  = false # no public IP
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 14
        retention_unit   = "COUNT"
      }
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 4
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = false
      record_client_address   = false
    }

    database_flags {
      name  = "max_connections"
      value = "200"
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "1000" # log queries slower than 1 s
    }
  }
}

resource "google_sql_database" "taskorbit" {
  name     = "taskorbit"
  instance = google_sql_database_instance.main.name
  project  = var.project_id
}

resource "google_sql_user" "app" {
  name     = "taskorbit"
  instance = google_sql_database_instance.main.name
  password = random_password.db.result
  project  = var.project_id
}
