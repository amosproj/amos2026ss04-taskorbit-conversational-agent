# ── Enable GCP APIs ───────────────────────────────────────────────────────────

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
  ]
}

resource "google_project_service" "apis" {
  for_each = toset(local.required_apis)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# ── Networking ────────────────────────────────────────────────────────────────

module "network" {
  source = "./modules/network"

  project_id = var.project_id
  region     = var.region

  depends_on = [google_project_service.apis]
}

# ── IAM / Service Accounts ────────────────────────────────────────────────────

module "iam" {
  source = "./modules/iam"

  project_id        = var.project_id
  github_repository = var.github_repository

  depends_on = [google_project_service.apis]
}

# ── Artifact Registry ─────────────────────────────────────────────────────────

module "registry" {
  source = "./modules/registry"

  project_id = var.project_id
  region     = var.region

  depends_on = [google_project_service.apis]
}

# ── Cloud SQL (PostgreSQL 16) ─────────────────────────────────────────────────

module "database" {
  source = "./modules/database"

  project_id = var.project_id
  region     = var.region
  network_id = module.network.vpc_id

  depends_on = [module.network, google_project_service.apis]
}

# ── Secret Manager ────────────────────────────────────────────────────────────

module "secrets" {
  source = "./modules/secrets"

  project_id = var.project_id

  livekit_url           = var.livekit_url
  livekit_api_key       = var.livekit_api_key
  livekit_api_secret    = var.livekit_api_secret
  deepgram_api_key      = var.deepgram_api_key
  deepgram_model        = var.deepgram_model
  deepgram_language     = var.deepgram_language
  elevenlabs_api_key    = var.elevenlabs_api_key
  elevenlabs_voice_id   = var.elevenlabs_voice_id
  elevenlabs_model      = var.elevenlabs_model
  openai_api_key        = var.openai_api_key
  openai_model          = var.openai_model
  google_api_key        = var.google_api_key
  google_model          = var.google_model
  database_url          = module.database.connection_string
  grafana_admin_password = var.grafana_admin_password

  depends_on = [module.database, google_project_service.apis]
}

# ── Cloud Run services ────────────────────────────────────────────────────────

module "cloud_run" {
  source = "./modules/cloud_run"

  project_id = var.project_id
  region     = var.region
  domain     = var.domain

  backend_image  = var.backend_image
  frontend_image = var.frontend_image

  backend_sa_email  = module.iam.backend_sa_email
  worker_sa_email   = module.iam.worker_sa_email
  frontend_sa_email = module.iam.frontend_sa_email

  vpc_connector_id               = module.network.vpc_connector_id
  cloud_sql_connection_name      = module.database.instance_connection_name

  secret_ids = module.secrets.secret_ids

  backend_min_instances  = var.backend_min_instances
  backend_max_instances  = var.backend_max_instances
  worker_min_instances   = var.worker_min_instances
  worker_max_instances   = var.worker_max_instances
  frontend_min_instances = var.frontend_min_instances
  frontend_max_instances = var.frontend_max_instances

  cors_allow_origins = var.cors_allow_origins

  depends_on = [module.iam, module.secrets, module.database, module.network]
}

# ── Observability (Prometheus + Loki + Grafana) ───────────────────────────────

module "observability" {
  source = "./modules/observability"

  project_id = var.project_id
  region     = var.region
  domain     = var.domain

  backend_sa_email  = module.iam.backend_sa_email
  worker_sa_email   = module.iam.worker_sa_email
  observability_sa_email = module.iam.observability_sa_email

  secret_ids = module.secrets.secret_ids

  backend_url = module.cloud_run.backend_url
  worker_url  = module.cloud_run.worker_url

  depends_on = [module.cloud_run, module.iam, google_project_service.apis]
}
