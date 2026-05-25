# Terraform — TaskOrbit GCP Infrastructure

This directory contains all Infrastructure as Code for the TaskOrbit GCP
environment. Running `terraform apply` provisions every resource the application
needs — network, database, secrets, container registry, Cloud Run services,
cost-saving scheduler, and observability stack.

---

## Directory Structure

```
terraform/
├── main.tf                  # Module wiring and API enablement
├── variables.tf             # All input variables with validation
├── outputs.tf               # Values needed post-apply (URLs, SA emails, LB IP)
├── versions.tf              # Provider version pins (google ~6.0, random ~3.6)
├── backend.tf               # Remote state — GCS bucket (fill placeholder before init)
├── terraform.tfvars.example # Template — copy to terraform.tfvars and fill in secrets
├── tests/                   # Native Terraform tests (terraform test)
│   ├── cloud_run.tftest.hcl
│   ├── observability.tftest.hcl
│   ├── scheduler.tftest.hcl
│   ├── secrets.tftest.hcl
│   └── variables.tftest.hcl
└── modules/
    ├── network/             # VPC, subnet, Cloud Router, NAT, VPC connector
    ├── iam/                 # Service accounts, IAM bindings, Workload Identity
    ├── registry/            # Artifact Registry repository
    ├── database/            # Cloud SQL PostgreSQL 16 (private IP, HA, PITR)
    ├── secrets/             # Secret Manager — 15 secrets prefixed taskorbit-
    ├── cloud_run/           # 3 Cloud Run v2 services + Global HTTPS LB
    ├── scheduler/           # Cloud Scheduler — SQL stop/start, worker scale-down
    └── observability/       # Prometheus + Loki + Grafana on Cloud Run
```

---

## Prerequisites

| Tool | Minimum version | Install |
|---|---|---|
| Terraform | 1.7 | `brew install terraform` |
| gcloud CLI | any recent | `brew install --cask google-cloud-sdk` |
| Docker | any recent | Docker Desktop |

---

## First-time Setup

### 1. Create the remote state bucket

The GCS bucket for Terraform state must exist before `terraform init`.
Replace the placeholder in `backend.tf` first:

```bash
PROJECT_ID="your-gcp-project-id"

gsutil mb -l europe-west1 gs://${PROJECT_ID}-taskorbit-tf-state
gsutil versioning set on gs://${PROJECT_ID}-taskorbit-tf-state
```

Edit `backend.tf`:
```hcl
bucket = "your-gcp-project-id-taskorbit-tf-state"
```

### 2. Create your tfvars file

```bash
cp terraform.tfvars.example terraform.tfvars
# Fill in all values — terraform.tfvars is git-ignored, never commit it
```

### 3. Initialise and apply

```bash
gcloud auth application-default login
terraform init
terraform plan
terraform apply
```

First apply takes ~15 minutes (Cloud SQL provisioning dominates).

---

## Outputs

After a successful apply, collect these values:

```bash
terraform output workload_identity_provider   # → GCP_WORKLOAD_IDENTITY_PROVIDER GitHub secret
terraform output cicd_service_account_email   # → GCP_SA_EMAIL GitHub secret
terraform output load_balancer_ip             # → DNS A record target
terraform output database_instance_name       # → for Cloud SQL Auth Proxy
terraform output artifact_registry_url        # → Docker push target
terraform output backend_url                  # → api.<domain>
terraform output frontend_url                 # → <domain>
terraform output grafana_url                  # → grafana.<domain>
```

---

## Modules

### `network`
Creates a VPC with a single subnet, a Cloud Router and NAT gateway for egress,
and a Serverless VPC Access connector so Cloud Run services can reach Cloud SQL
over private IP. All egress is set to `PRIVATE_RANGES_ONLY`.

### `iam`
Creates five service accounts (backend, worker, frontend, observability, cicd)
and binds the minimum required roles to each. Also provisions a Workload Identity
Federation pool and provider scoped to this GitHub repository so GitHub Actions
can authenticate via OIDC without any long-lived key.

### `registry`
Creates an Artifact Registry Docker repository named `taskorbit` in `europe-west1`.
Built images are pushed here by the CI/CD pipeline.

### `database`
Cloud SQL PostgreSQL 16 with:
- No public IP (`ipv4_enabled = false`) — reachable only via VPC or Cloud SQL Auth Proxy
- Regional high-availability with automatic failover
- Daily backups, 14 retained, point-in-time recovery enabled (7-day log window)
- `deletion_protection = true` — prevents accidental destruction via `terraform destroy`

### `secrets`
Creates 15 Secret Manager secrets, all prefixed `taskorbit-`, using a `for_each`
loop. The `lifecycle { ignore_changes = [secret_data] }` block means Terraform
never overwrites a secret version after creation — rotate keys with
`gcloud secrets versions add` instead.

### `cloud_run`
Deploys three Cloud Run v2 services behind a Global HTTPS load balancer with
a managed SSL certificate:
- `taskorbit-backend` — FastAPI API (port 8000)
- `taskorbit-worker` — LiveKit voice agent (port 8001)
- `taskorbit-frontend` — React bundle served by nginx (port 80)

All services connect to Cloud SQL via a shared Unix socket volume and read
secrets as environment variables injected from Secret Manager at startup.

### `scheduler`
Cloud Scheduler jobs that reduce idle costs:
- `taskorbit-sql-stop` — sets Cloud SQL `activationPolicy=NEVER` at 22:00 Mon–Fri (CET)
- `taskorbit-sql-start` — restores `activationPolicy=ALWAYS` at 07:00 Mon–Fri (CET)
- `taskorbit-worker-scale-down` / `scale-up` — optional, controlled by `scale_worker_overnight`

Cloud Run services scale to 0 automatically when idle (built-in behaviour, no config needed).

### `observability`
Runs Prometheus, Loki, and Grafana as Cloud Run services. Prometheus scrapes
`/metrics` on the backend and worker using OIDC authentication. Loki stores
logs in a GCS bucket. Grafana is exposed at `grafana.<domain>`.

---

## Running Tests

Tests use Terraform's native test framework and `mock_provider` — no GCP
credentials or live project required.

```bash
cd terraform

# Run all tests
terraform test

# Run a single test file
terraform test -filter=tests/scheduler.tftest.hcl
terraform test -filter=tests/secrets.tftest.hcl
terraform test -filter=tests/variables.tftest.hcl
terraform test -filter=tests/cloud_run.tftest.hcl
terraform test -filter=tests/observability.tftest.hcl
```

| Test file | What it covers |
|---|---|
| `tests/scheduler.tftest.hcl` | `count` logic for the boolean flags (`enable_auto_shutdown`, `scale_worker_overnight`) and default cron schedule values |
| `tests/secrets.tftest.hcl` | All 15 secrets are created, `taskorbit-` prefix enforced, correct labels applied |
| `tests/variables.tftest.hcl` | Validation blocks reject bad inputs (wrong scheme, empty required fields, weak password, impossible scaling range) |
| `tests/cloud_run.tftest.hcl` | Ingress settings per service, CORS origin fallback and override, SSL cert domain coverage, frontend `BACKEND_URL` env |
| `tests/observability.tftest.hcl` | Loki/Prometheus internal-only ingress, GCS bucket naming and retention, Pub/Sub push subscription wiring, Grafana SSL cert domain |

---

## Cost Controls

| Mechanism | Saves |
|---|---|
| Cloud SQL auto-stop (22:00–07:00 Mon–Fri) | vCPU + RAM billing paused overnight |
| Cloud Run scales to 0 when idle | No instances billed when no traffic |
| `worker_min_instances = 1` (default) | Worker stays alive for LiveKit; set to 0 via `scale_worker_overnight` if 24/7 not needed |
| `db-custom-2-7680` tier | Right-sized for development; upgrade in `modules/database/variables.tf` for production load |

---

## Security Notes

- **No long-lived service account keys** — CI/CD authenticates via Workload Identity Federation (OIDC). See `modules/iam/main.tf`.
- **No public database IP** — Cloud SQL is only reachable via VPC connector (Cloud Run) or Cloud SQL Auth Proxy (local dev).
- **Secrets never in code** — all API keys live in Secret Manager; `terraform.tfvars` is git-ignored.
- **Deletion protection** — Cloud SQL has `deletion_protection = true`. Remove it manually before `terraform destroy`.
- **Repository-scoped WIF** — the `attribute_condition` in the Workload Identity provider restricts authentication to this repository only.

---

## SBOM

A Software Bill of Materials documents every dependency this infrastructure
layer pulls in — Terraform providers, their transitive dependencies, and the
versions pinned in `.terraform.lock.hcl`.

Generate a CycloneDX JSON SBOM locally using [Syft](https://github.com/anchore/syft):

```bash
# Install Syft (macOS)
brew install syft

# Generate SBOM from the terraform/ directory
syft dir:. \
  --exclude './.terraform/**' \
  -o cyclonedx-json \
  > sbom.cyclonedx.json
```

The `.terraform.lock.hcl` file (committed to the repo) is the authoritative
pin record for provider versions. The SBOM adds machine-readable metadata
(checksums, package URLs) on top of it. Commit `sbom.cyclonedx.json` to the
repo root whenever the provider versions change (i.e. after `terraform init -upgrade`).

---

## Common Commands

```bash
# Initialise (after editing backend.tf placeholder)
terraform init

# Preview changes
terraform plan

# Apply changes
terraform apply

# Run unit tests (no GCP credentials needed)
terraform test

# Destroy all resources (remove deletion_protection first)
terraform destroy

# Format all .tf files
terraform fmt -recursive

# Validate configuration without a backend
terraform validate

# Refresh outputs after a manual GCP change
terraform refresh
```
