# ── STEP 1 (ACTIVE): Enable GCP APIs ─────────────────────────────────────────
# Everything else depends on these being enabled first.
# Run: terraform apply -target=google_project_service.apis

locals {
  required_apis = [
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "storage.googleapis.com",
    "vpcaccess.googleapis.com",
    "pubsub.googleapis.com",
    "logging.googleapis.com",
    "cloudscheduler.googleapis.com",
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ── STEP 2 (ACTIVE): Networking ──────────────────────────────────────────────
# VPC, subnet, Cloud NAT, Serverless VPC connector, private service access.
# Depends on: Step 1 (APIs)
# Run: terraform apply -target=module.network

module "network" {
  source = "./modules/network"

  project_id = var.project_id
  region     = var.region

  depends_on = [google_project_service.apis]
}

# ── STEP 3 (ACTIVE): IAM / Service Accounts ──────────────────────────────────
# Service accounts, IAM bindings, GitHub Actions Workload Identity (OIDC).
# Depends on: Step 1 (APIs) — no dependency on network
# Run: terraform apply -target=module.iam

module "iam" {
  source = "./modules/iam"

  project_id        = var.project_id
  github_repository = var.github_repository

  depends_on = [google_project_service.apis]
}

# ── STEP 4 (COMMENTED): Artifact Registry ────────────────────────────────────
# Docker repository for backend and frontend container images.
# Depends on: Step 1 (APIs)
# Run: terraform apply -target=module.registry
#
# module "registry" {
#   source = "./modules/registry"
#
#   project_id = var.project_id
#   region     = var.region
#
#   depends_on = [google_project_service.apis]
# }

# ── STEP 5 (COMMENTED): Cloud SQL (PostgreSQL 16) ────────────────────────────
# Regional HA database, private IP only, automated backups + PITR.
# Depends on: Step 2 (network — private service access must exist first)
# WARNING: takes 5–10 min to provision — do NOT cancel mid-apply.
# Run: terraform apply -target=module.database
#
# module "database" {
#   source = "./modules/database"
#
#   project_id = var.project_id
#   region     = var.region
#   network_id = module.network.vpc_id
#
#   depends_on = [module.network, google_project_service.apis]
# }

# ── STEP 6 (COMMENTED): Secret Manager ───────────────────────────────────────
# All API keys and the DB connection string stored as secrets.
# Depends on: Step 5 (database — DB connection string is a secret value)
# Run: terraform apply -target=module.secrets
#
# module "secrets" {
#   source = "./modules/secrets"
#
#   project_id = var.project_id
#
#   livekit_url            = var.livekit_url
#   livekit_api_key        = var.livekit_api_key
#   livekit_api_secret     = var.livekit_api_secret
#   deepgram_api_key       = var.deepgram_api_key
#   deepgram_model         = var.deepgram_model
#   deepgram_language      = var.deepgram_language
#   elevenlabs_api_key     = var.elevenlabs_api_key
#   elevenlabs_voice_id    = var.elevenlabs_voice_id
#   elevenlabs_model       = var.elevenlabs_model
#   openai_api_key         = var.openai_api_key
#   openai_model           = var.openai_model
#   google_api_key         = var.google_api_key
#   google_model           = var.google_model
#   database_url           = module.database.connection_string
#   grafana_admin_password = var.grafana_admin_password
#
#   depends_on = [module.database, google_project_service.apis]
# }

# ── STEP 7 (COMMENTED): Cloud Run Services + Load Balancer ───────────────────
# Backend, worker, frontend Cloud Run services; global HTTPS load balancer.
# Depends on: Steps 2 (network), 3 (iam), 5 (database), 6 (secrets)
# AFTER APPLY: note load_balancer_ip output and create DNS A records:
#   your-domain.com       → load_balancer_ip
#   api.your-domain.com   → load_balancer_ip
# Run: terraform apply -target=module.cloud_run
#
# module "cloud_run" {
#   source = "./modules/cloud_run"
#
#   project_id = var.project_id
#   region     = var.region
#   domain     = var.domain
#
#   backend_image  = var.backend_image
#   frontend_image = var.frontend_image
#
#   backend_sa_email  = module.iam.backend_sa_email
#   worker_sa_email   = module.iam.worker_sa_email
#   frontend_sa_email = module.iam.frontend_sa_email
#
#   vpc_connector_id          = module.network.vpc_connector_id
#   cloud_sql_connection_name = module.database.instance_connection_name
#
#   secret_ids = module.secrets.secret_ids
#
#   backend_min_instances  = var.backend_min_instances
#   backend_max_instances  = var.backend_max_instances
#   worker_min_instances   = var.worker_min_instances
#   worker_max_instances   = var.worker_max_instances
#   frontend_min_instances = var.frontend_min_instances
#   frontend_max_instances = var.frontend_max_instances
#
#   cors_allow_origins = var.cors_allow_origins
#
#   depends_on = [module.iam, module.secrets, module.database, module.network]
# }

# ── STEP 8 (COMMENTED): Auto-shutdown Scheduler ───────────────────────────────
# Cloud Scheduler stops Cloud SQL at 22:00 Mon–Fri and restarts at 07:00 (CET).
# Depends on: Step 5 (database — needs instance name)
# Run: terraform apply -target=module.scheduler
#
# module "scheduler" {
#   source = "./modules/scheduler"
#
#   project_id       = var.project_id
#   region           = var.region
#   db_instance_name = module.database.instance_name
#
#   enable_auto_shutdown   = var.enable_auto_shutdown
#   scale_worker_overnight = var.scale_worker_overnight
#
#   depends_on = [module.database, google_project_service.apis]
# }

# ── STEP 9 (COMMENTED): Observability (Prometheus + Loki + Grafana) ───────────
# Scrapes backend/worker metrics, aggregates logs, Grafana dashboards.
# Depends on: Step 7 (cloud_run — needs service URLs for Prometheus scrape config)
# NOTE: DNS for grafana.your-domain.com → grafana_lb_ip must be set before this
#       so the managed SSL certificate can provision successfully.
# Run: terraform apply -target=module.observability
#
# module "observability" {
#   source = "./modules/observability"
#
#   project_id = var.project_id
#   region     = var.region
#   domain     = var.domain
#
#   backend_sa_email       = module.iam.backend_sa_email
#   worker_sa_email        = module.iam.worker_sa_email
#   observability_sa_email = module.iam.observability_sa_email
#
#   secret_ids = module.secrets.secret_ids
#
#   backend_url = module.cloud_run.backend_url
#   worker_url  = module.cloud_run.worker_url
#
#   depends_on = [module.cloud_run, module.iam, google_project_service.apis]
# }

# ── STEP 10 (FINAL): Full apply ───────────────────────────────────────────────
# After all steps above are done and DNS is verified, run a bare apply
# to catch any inter-module dependencies that were missed above.
# Expect: 0 changes (or only minor computed-value refreshes).
# Run: terraform apply
