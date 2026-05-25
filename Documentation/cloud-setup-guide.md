# GCP Cloud Setup — TaskOrbit Conversational Agent

> **Scope.** This guide covers the one-time Terraform bootstrap, how the deploy
> pipeline authenticates to GCP without long-lived keys, how secrets are stored
> and consumed by Cloud Run, and how developers can authenticate locally.
>
> For the lint/test/smoke pipeline see `Documentation/ci-cd.md`.
> For LiveKit credential generation and local Docker Compose setup see
> `Documentation/livekit-cloud-setup.md`.
> For the full Terraform variable reference see `terraform/terraform.tfvars.example`.
> For the Terraform module reference see `terraform/README.md`.

---

## Prerequisites

- **Terraform >= 1.7** (matches `terraform/versions.tf`)
- **gcloud CLI** authenticated as a GCP project owner for the initial bootstrap
- **Docker** (needed for the CI/CD pipeline to build images)
- A **GCP project with billing enabled**
- The repository cloned and `terraform/terraform.tfvars` created from
  `terraform/terraform.tfvars.example` with real values filled in

---

## 1. One-time Bootstrap

These steps run once per environment. After they complete, all future deployments
are handled automatically by the CI/CD pipeline.

### 1.1 Create the Terraform state bucket

Terraform records the state of every resource it manages in a GCS bucket.
This bucket must exist before running `terraform init`. The bucket name is
currently a placeholder in `terraform/backend.tf` — replace it first.

```bash
PROJECT_ID="your-gcp-project-id"
REGION="europe-west1"

# Create the state bucket (one-time only)
gsutil mb -l ${REGION} gs://${PROJECT_ID}-taskorbit-tf-state

# Enable versioning so previous state files are preserved
gsutil versioning set on gs://${PROJECT_ID}-taskorbit-tf-state
```

Then open `terraform/backend.tf` and replace the placeholder:

```hcl
# Before
bucket = "REPLACE_WITH_PROJECT_ID-taskorbit-tf-state"

# After
bucket = "your-gcp-project-id-taskorbit-tf-state"
```

### 1.2 Provision all GCP infrastructure

`terraform apply` enables the required APIs and creates all resources across
8 modules (network, IAM, registry, database, secrets, Cloud Run, scheduler,
observability). First-run takes approximately 15 minutes — Cloud SQL provisioning
dominates.

```bash
# Authenticate as a project owner
gcloud auth application-default login
gcloud config set project ${PROJECT_ID}

cd terraform

# Download providers and connect to the remote state bucket
terraform init

# Review what will be created before applying
terraform plan -out=tfplan

# Apply — creates ~50 resources
terraform apply tfplan
```

> **Note on deletion protection.** Cloud SQL is created with
> `deletion_protection = true` (see `terraform/modules/database/main.tf`).
> Running `terraform destroy` will fail until you manually set that flag to
> `false` and re-apply. This is intentional to prevent accidental data loss.

### 1.3 Capture outputs for the next steps

After a successful apply, collect the values you need for DNS and GitHub:

```bash
# For GitHub Actions secrets (see Section 3.2)
terraform output workload_identity_provider
terraform output cicd_service_account_email

# For DNS configuration
terraform output load_balancer_ip

# For local Cloud SQL access (see Section 5.3)
terraform output database_instance_name
```

### 1.4 Point DNS to the load balancer

Create DNS **A records** at your domain registrar pointing all three subdomains
to the IP from `terraform output load_balancer_ip`:

| Subdomain | Purpose |
|---|---|
| `taskorbit.yourdomain.com` | React frontend |
| `api.taskorbit.yourdomain.com` | FastAPI backend |
| `grafana.taskorbit.yourdomain.com` | Grafana dashboards |

The managed SSL certificate Google provisions will stay in `PROVISIONING` state
until DNS propagates (usually 10–30 minutes).

---

## 2. What Terraform Provisions

For reference, this table maps each Terraform module to the GCP resources it creates:

| Module | GCP resources | Key file |
|---|---|---|
| `network` | VPC, subnet, Cloud Router, NAT gateway, VPC connector | `terraform/modules/network/main.tf` |
| `iam` | 5 service accounts, Workload Identity pool + provider, IAM bindings | `terraform/modules/iam/main.tf` |
| `registry` | Artifact Registry repository `taskorbit` (europe-west1) | `terraform/modules/registry/main.tf` |
| `database` | Cloud SQL PostgreSQL 16, private IP only, regional HA, PITR backups | `terraform/modules/database/main.tf` |
| `secrets` | 15 Secret Manager secrets prefixed `taskorbit-` | `terraform/modules/secrets/main.tf` |
| `cloud_run` | 3 Cloud Run v2 services + Global HTTPS load balancer | `terraform/modules/cloud_run/main.tf` |
| `scheduler` | Cloud Scheduler jobs: SQL stop (22:00 CET) / start (07:00 CET) Mon–Fri | `terraform/modules/scheduler/main.tf` |
| `observability` | Prometheus + Loki + Grafana on Cloud Run, GCS bucket for logs | `terraform/modules/observability/main.tf` |

---

## 3. CI/CD Authentication — Workload Identity Federation

### 3.1 How it works

The deploy pipeline uses **Workload Identity Federation (WIF)** so GitHub Actions
never needs a permanent GCP service account key. Instead:

1. When a push lands on `main`, GitHub's OIDC provider
   (`https://token.actions.githubusercontent.com`) issues a short-lived JWT
   that identifies the repository and workflow run.
2. The `google-github-actions/auth@v2` step sends that JWT to the GCP Workload
   Identity pool (`github-pool/providers/github-provider`) created by
   `terraform/modules/iam/main.tf`.
3. GCP verifies the JWT and checks the `attribute_condition`:
   ```hcl
   attribute_condition = "assertion.repository == 'amosproj/amos2026ss04-taskorbit-conversational-agent'"
   ```
   This ensures only this repository can use the pool — no other GitHub repo
   can impersonate the `taskorbit-cicd` service account.
4. GCP exchanges the JWT for a short-lived access token scoped to
   `taskorbit-cicd`, which holds only the permissions it needs:
   `roles/artifactregistry.writer`, `roles/run.admin`,
   `roles/iam.serviceAccountUser`.

No long-lived key is ever created or stored. The token expires after the workflow run.

The deploy only fires after all three quality-gate workflows (**Backend Linting**,
**Frontend Linting**, **Start Web Service**) pass on `main` — see
`.github/workflows/deploy.yml`.

### 3.2 Configure the three required GitHub secrets

These must be set in the repository under **Settings → Secrets and variables → Actions**
(source: header comment in `.github/workflows/deploy.yml`):

| Secret name | How to get the value |
|---|---|
| `GCP_PROJECT_ID` | Your GCP project ID (plain string) |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | `cd terraform && terraform output -raw workload_identity_provider` |
| `GCP_SA_EMAIL` | `cd terraform && terraform output -raw cicd_service_account_email` |

Using the GitHub CLI:

```bash
gh secret set GCP_PROJECT_ID --body "${PROJECT_ID}"

gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER \
  --body "$(cd terraform && terraform output -raw workload_identity_provider)"

gh secret set GCP_SA_EMAIL \
  --body "$(cd terraform && terraform output -raw cicd_service_account_email)"
```

### 3.3 What the deploy workflow does

On every push to `main` (after quality gates pass):

1. **build job** — authenticates to GCP via WIF, builds `backend` and `frontend`
   Docker images at the `prod` target, and pushes each with two tags:
   `sha-<commit>` (immutable) and `latest`.
2. **deploy job** — re-authenticates, then deploys all three Cloud Run services:
   `taskorbit-backend`, `taskorbit-worker` (reuses the backend image), and
   `taskorbit-frontend`.

---

## 4. Secrets Management

### 4.1 How secrets are created

`terraform/modules/secrets/main.tf` uses a `for_each` over `local.app_secrets`
to create 15 secrets in Secret Manager, all prefixed `taskorbit-`:

| Secret Manager ID | Holds |
|---|---|
| `taskorbit-livekit-url` | LiveKit Cloud WSS URL |
| `taskorbit-livekit-api-key` | LiveKit API key |
| `taskorbit-livekit-api-secret` | LiveKit API secret |
| `taskorbit-deepgram-api-key` | Deepgram API key |
| `taskorbit-deepgram-model` | e.g. `nova-3` |
| `taskorbit-deepgram-language` | e.g. `multi` |
| `taskorbit-elevenlabs-api-key` | ElevenLabs API key |
| `taskorbit-elevenlabs-voice-id` | Voice ID |
| `taskorbit-elevenlabs-model` | Model name |
| `taskorbit-openai-api-key` | OpenAI key (optional) |
| `taskorbit-openai-model` | e.g. `gpt-4o-mini` |
| `taskorbit-google-api-key` | Google AI key (optional) |
| `taskorbit-google-model` | e.g. `gemini-2.5-flash` |
| `taskorbit-database-url` | PostgreSQL connection string (computed by Terraform) |
| `taskorbit-grafana-admin-password` | Grafana admin password |

### 4.2 How Cloud Run services read secrets

Each secret is injected into Cloud Run as an environment variable at instance
startup via `secret_key_ref` pointing to `version = "latest"`. The backend and
worker service accounts hold `roles/secretmanager.secretAccessor`
(`terraform/modules/iam/main.tf`), which grants them read access.

| Environment variable | Secret Manager ID |
|---|---|
| `DATABASE_URL` | `taskorbit-database-url` |
| `LIVEKIT_URL` | `taskorbit-livekit-url` |
| `LIVEKIT_API_KEY` | `taskorbit-livekit-api-key` |
| `LIVEKIT_API_SECRET` | `taskorbit-livekit-api-secret` |
| `DEEPGRAM_API_KEY` | `taskorbit-deepgram-api-key` |
| `ELEVENLABS_API_KEY` | `taskorbit-elevenlabs-api-key` |
| `OPENAI_API_KEY` | `taskorbit-openai-api-key` |
| `GOOGLE_API_KEY` | `taskorbit-google-api-key` |

### 4.3 Rotating a secret without Terraform drift

`terraform/modules/secrets/main.tf` includes `lifecycle { ignore_changes = [secret_data] }`
so Terraform never overwrites a secret version after creation. To rotate:

```bash
# Add a new version
echo -n "NEW_VALUE" | \
  gcloud secrets versions add taskorbit-openai-api-key \
  --project="${PROJECT_ID}" \
  --data-file=-

# Redeploy so running instances pick up "latest"
gcloud run services update taskorbit-backend \
  --region=europe-west1 \
  --project="${PROJECT_ID}"
```

### 4.4 Viewing a secret value

```bash
gcloud secrets versions access latest \
  --secret="taskorbit-openai-api-key" \
  --project="${PROJECT_ID}"
```

---

## 5. Local Developer Authentication

### 5.1 Application Default Credentials

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login
```

After this, Terraform, the Python SDK, and gcloud commands all use your
personal identity automatically — no service account key file needed.

### 5.2 Reading secrets locally

```bash
gcloud secrets versions access latest \
  --secret="taskorbit-openai-api-key" \
  --project="${PROJECT_ID}"
```

Use these values to populate `backend/.env` for local development
(see `Documentation/livekit-cloud-setup.md` for the full local setup steps).

### 5.3 Connecting to Cloud SQL locally

Cloud SQL has no public IP (`ipv4_enabled = false` in
`terraform/modules/database/main.tf`). Use the **Cloud SQL Auth Proxy**:

```bash
# Install (macOS Apple Silicon)
curl -o cloud-sql-proxy \
  https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy/v2.14.1/cloud-sql-proxy.darwin.arm64
chmod +x cloud-sql-proxy

# Full connection name: PROJECT_ID:REGION:INSTANCE_NAME
cd terraform && terraform output -raw database_instance_name
# e.g. taskorbit-postgres → my-project:europe-west1:taskorbit-postgres

# Start the proxy (uses ADC automatically)
./cloud-sql-proxy --port=5432 \
  "${PROJECT_ID}:europe-west1:taskorbit-postgres"
```

Retrieve the database password from the secret:

```bash
gcloud secrets versions access latest \
  --secret="taskorbit-database-url" \
  --project="${PROJECT_ID}" | \
  python3 -c "import sys, urllib.parse; u=sys.stdin.read().strip(); print(urllib.parse.urlparse(u).password)"
```

### 5.4 Minimum IAM roles for a developer

| Role | Why |
|---|---|
| `roles/secretmanager.secretAccessor` | Read secrets locally |
| `roles/cloudsql.client` | Use Cloud SQL Auth Proxy |
| `roles/run.viewer` | View Cloud Run service logs and status |

A project owner grants these with:

```bash
DEV_EMAIL="developer@example.com"

for ROLE in \
  roles/secretmanager.secretAccessor \
  roles/cloudsql.client \
  roles/run.viewer; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="user:${DEV_EMAIL}" \
    --role="${ROLE}"
done
```

---

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `terraform init` fails: `bucket does not exist` | GCS state bucket not created yet | Run `gsutil mb` in Section 1.1 first |
| `403 Permission denied` on `terraform apply` | ADC user is not a project owner | Run `gcloud auth application-default login` as a project owner |
| GitHub Actions: `google-github-actions/auth failed` | `GCP_WORKLOAD_IDENTITY_PROVIDER` secret is wrong | Re-run `terraform output -raw workload_identity_provider` and update the secret |
| GitHub Actions: `Permission denied` on Artifact Registry push | `GCP_SA_EMAIL` is wrong or WIF pool misconfigured | Verify both secrets; check `attribute_condition` matches your repo slug |
| Cloud Run fails to start: `Secret not found` | Secret name typo or secrets module not applied | Check with `gcloud secrets list --filter="name~taskorbit" --project="${PROJECT_ID}"` |
| `psql: Connection refused` on port 5432 locally | Cloud SQL Auth Proxy not running | Start the proxy as shown in Section 5.3 |
| SSL certificate stays `PROVISIONING` | DNS A records not yet pointing to `load_balancer_ip` | Check DNS propagation; GCP polls for DNS before issuing the cert |
| `terraform destroy` fails on Cloud SQL | `deletion_protection = true` | Set to `false` in `terraform/modules/database/main.tf`, re-apply, then destroy |
| Rotated secret but Cloud Run still uses old value | Secrets are cached at instance startup | Run `gcloud run services update` to force a new revision |

---

## 7. Quick Reference

```bash
# ── One-time bootstrap ────────────────────────────────────────────────────────
gsutil mb -l europe-west1 gs://${PROJECT_ID}-taskorbit-tf-state
gsutil versioning set on gs://${PROJECT_ID}-taskorbit-tf-state
# Edit terraform/backend.tf — replace REPLACE_WITH_PROJECT_ID
gcloud auth application-default login
cd terraform && terraform init && terraform apply

# ── Capture outputs for GitHub secrets ───────────────────────────────────────
terraform output -raw workload_identity_provider   # → GCP_WORKLOAD_IDENTITY_PROVIDER
terraform output -raw cicd_service_account_email   # → GCP_SA_EMAIL
terraform output load_balancer_ip                  # → DNS A record target

# ── Set GitHub Actions secrets ────────────────────────────────────────────────
gh secret set GCP_PROJECT_ID --body "${PROJECT_ID}"
gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body "$(terraform output -raw workload_identity_provider)"
gh secret set GCP_SA_EMAIL --body "$(terraform output -raw cicd_service_account_email)"

# ── Rotate a secret ───────────────────────────────────────────────────────────
echo -n "NEW_VALUE" | gcloud secrets versions add taskorbit-<key> \
  --project="${PROJECT_ID}" --data-file=-
gcloud run services update taskorbit-backend --region=europe-west1 --project="${PROJECT_ID}"

# ── Read a secret locally ─────────────────────────────────────────────────────
gcloud secrets versions access latest --secret="taskorbit-openai-api-key" \
  --project="${PROJECT_ID}"

# ── Connect to Cloud SQL locally ──────────────────────────────────────────────
./cloud-sql-proxy --port=5432 "${PROJECT_ID}:europe-west1:taskorbit-postgres"
psql "host=127.0.0.1 port=5432 dbname=taskorbit user=taskorbit"
```
