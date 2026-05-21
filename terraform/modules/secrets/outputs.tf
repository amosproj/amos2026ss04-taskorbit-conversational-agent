output "secret_ids" {
  description = "Map of key → Secret Manager secret_id (short form, e.g. 'taskorbit-database-url')."
  value       = { for k, v in google_secret_manager_secret.secrets : k => v.secret_id }
}
