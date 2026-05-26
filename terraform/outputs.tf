# Outputs are commented out to match the incremental apply strategy in main.tf.
# Uncomment each output when the corresponding module is enabled.

# ── STEP 4 (ACTIVE): Artifact Registry ───────────────────────────────────────
output "artifact_registry_url" {
  description = "Artifact Registry Docker repository URL."
  value       = module.registry.repository_url
}

# ── STEP 5 (ACTIVE): Database ────────────────────────────────────────────────
output "database_instance_name" {
  description = "Cloud SQL instance name (for connecting via Cloud SQL proxy)."
  value       = module.database.instance_name
}

# ── STEP 3 (ACTIVE): IAM ─────────────────────────────────────────────────────
output "cicd_service_account_email" {
  description = "CI/CD service account email — configure as GitHub Actions secret GCP_SA_EMAIL."
  value       = module.iam.cicd_sa_email
}

output "workload_identity_provider" {
  description = "Workload Identity provider resource name — configure as GitHub Actions secret GCP_WORKLOAD_IDENTITY_PROVIDER."
  value       = module.iam.workload_identity_provider
}

# ── STEP 7 (ACTIVE): Cloud Run + Load Balancer ───────────────────────────────
output "frontend_url" {
  description = "Public URL of the React frontend."
  value       = module.cloud_run.frontend_url
}

output "backend_url" {
  description = "Public URL of the FastAPI backend (api.<domain>)."
  value       = module.cloud_run.backend_url
}

output "worker_url" {
  description = "Internal Cloud Run URL of the LiveKit worker (metrics at /metrics)."
  value       = module.cloud_run.worker_url
}

output "load_balancer_ip" {
  description = "Global external IP — point your DNS A records here."
  value       = module.cloud_run.load_balancer_ip
}

# ── STEP 9 (ACTIVE): Observability ───────────────────────────────────────────
output "grafana_url" {
  description = "Grafana dashboard Cloud Run URL — open this in your browser to access Grafana."
  value       = module.observability.grafana_url
}

output "grafana_lb_ip" {
  description = "Grafana load balancer IP — only needed when a custom domain is configured."
  value       = module.observability.grafana_lb_ip
}
