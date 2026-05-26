output "instance_name" {
  value = google_sql_database_instance.main.name
}

output "instance_connection_name" {
  description = "Connection name in PROJECT:REGION:INSTANCE format — used by Cloud SQL proxy."
  value       = google_sql_database_instance.main.connection_name
}

output "private_ip" {
  value = google_sql_database_instance.main.private_ip_address
}

output "connection_string" {
  description = "PostgreSQL connection string via Unix socket (Cloud SQL proxy in Cloud Run)."
  value       = "postgresql://taskorbit:${random_password.db.result}@/taskorbit?host=/cloudsql/${google_sql_database_instance.main.connection_name}"
  sensitive   = true
}
