# Self-Hosted Inference (Ollama on GCE VM with NVIDIA L4)

TaskOrbit can run Gemma and Qwen models on a dedicated **NVIDIA L4 GPU** via an [Ollama](https://ollama.com) container on a Google Compute Engine VM. This keeps inference costs predictable, keeps data fully within your GCP project, and eliminates external API rate limits.

Self-hosted inference runs alongside the existing cloud providers (OpenAI, Gemini, OpenRouter) — you select it per-agent in the UI.

> **Why GCE VM instead of Cloud Run?** Cloud Run GPU nodes are locked to NVIDIA driver 535. Ollama 0.30+ requires driver 550+. GCE Deep Learning VM images ship with driver 580 and CUDA 12.9 pre-installed, enabling current model families (gemma4, qwen3).

---

## Architecture

```
TaskOrbit UI
    │ provider = "ollama"
    ▼
FastAPI backend / LiveKit worker
    │ OllamaClient — plain HTTP (no auth token needed)
    │ http://<static-ip>:11434
    ▼
GCE VM: g2-standard-8 (NVIDIA L4, 22 GiB VRAM)
  Docker container: ollama/ollama
    │ --gpus all
    │ models stored at /opt/ollama-models (local SSD)
    ▼
GCS bucket (backup/transfer store)
  <project_id>-ollama-models/
```

- **Auth:** None — the GCE VM uses a static external IP on port 11434 with a firewall rule scoped to `taskorbit-ollama` tagged instances. `OllamaClient._needs_auth = False`; no GCP identity token is fetched.
- **Models:** Stored on the VM's local SSD at `/opt/ollama-models` (mounted into the container at `/root/.ollama`). Local SSD gives fast random-read access for tensor loading (~10–15 s cold start vs 3+ minutes from GCSFuse).
- **GCS bucket:** Used as a persistent backup and transfer store — not mounted at runtime. Copy weights to/from the VM manually with `gsutil` or `docker exec`.
- **Thinking mode disabled:** `OllamaClient` sends `"think": false` at the top level of every `/api/chat` request. This suppresses extended thinking for Qwen3 and gemma4 model families so `content` is always populated.

---

## Supported Models

| Model | VRAM | Context | Notes |
|---|---|---|---|
| `gemma4:e4b` | ~6 GB | 128K | Lightest; fastest response |
| `gemma4:26b` | ~18 GB | 128K | **Default** — best speed/quality on L4 |
| `qwen3.5:9b` | ~7 GB | 32K | Compact Qwen; good for intent routing |
| `qwen3.6:27b` | ~17 GB | 256K | Best for long-context tasks |

All four models are pre-pulled on the current VM instance. Only one model is active at a time (set via `OLLAMA_MODEL` in backend `.env`).

---

## Prerequisites

- GCP project with NVIDIA L4 quota in the target zone (`us-east1-b` by default)
- `gcloud` CLI authenticated: `gcloud auth login`
- Terraform ≥ 1.7, `enable_gpu_inference = true` in `terraform.tfvars`

Request L4 GPU quota at: **GCP Console → IAM & Admin → Quotas** — search for `NVIDIA_L4_GPUS` in `us-east1`.

---

## 1 — Enable (First-Time Deploy)

### Step 1a — Configure Terraform

```hcl
# terraform/terraform.tfvars
enable_gpu_inference = true
gpu_inference_region = "us-east1"
gpu_inference_zone   = "us-east1-b"
ollama_version       = "latest"
ollama_model         = "gemma4:26b"
gpu_inference_models = ["gemma4:e4b", "gemma4:26b", "qwen3.6:27b", "qwen3.5:9b"]
```

### Step 1b — Apply

```bash
cd terraform
terraform apply -target=module.gpu_inference
```

This provisions the static IP, firewall rule, and GCE VM. The VM startup script automatically installs Docker, nvidia-container-toolkit, and starts the Ollama container.

### Step 1c — Note the static IP

```bash
terraform output -module=gpu_inference ollama_service_url
# e.g. http://35.231.129.211:11434
```

Set this as `OLLAMA_BASE_URL` in `backend/.env` for local dev, or update the secret in Secret Manager for Cloud Run.

### Step 1d — Pull models on the VM

```bash
# SSH into the VM
gcloud compute ssh taskorbit-ollama-inference --zone=us-east1-b

# Pull models (run inside the VM)
docker exec ollama ollama pull gemma4:26b
docker exec ollama ollama pull gemma4:e4b
docker exec ollama ollama pull qwen3.6:27b
docker exec ollama ollama pull qwen3.5:9b
```

Each pull downloads directly from the Ollama registry into `/opt/ollama-models` on the local SSD.

### Step 1e — Validate

```bash
# From your local machine
curl http://<static-ip>:11434/api/tags | jq '.models[].name'

# Or run the full validation script
./backend/scripts/validate_ollama_inference.sh
```

---

## 2 — Start and Stop

### Start the VM

```bash
gcloud compute instances start taskorbit-ollama-inference \
  --zone=us-east1-b --project=amos-taskorbit
```

The Ollama Docker container starts automatically via the `--restart unless-stopped` policy. The first inference request after a cold boot takes ~10–15 s for model loading.

### Stop the VM (save costs when idle)

```bash
gcloud compute instances stop taskorbit-ollama-inference \
  --zone=us-east1-b --project=amos-taskorbit
```

GCE billing stops immediately when the VM is stopped. Models on the local SSD are preserved across stop/start cycles (the disk is not deleted).

> **Cost:** A g2-standard-8 with NVIDIA L4 costs approximately $1.30/hour. Stopping overnight (14 h) and on weekends saves ~60% vs 24/7 operation.

---

## 3 — Swap the Active Model

Update `OLLAMA_MODEL` in `backend/.env` (local) or Secret Manager (Cloud Run):

```bash
# Local dev
echo "OLLAMA_MODEL=qwen3.6:27b" >> backend/.env

# Cloud Run (production)
echo -n "qwen3.6:27b" | gcloud secrets versions add ollama-model \
  --data-file=- --project=amos-taskorbit
```

The new model takes effect on the next backend restart. No Terraform change needed.

---

## 4 — Add a New Model

### Pull directly on the VM

```bash
gcloud compute ssh taskorbit-ollama-inference --zone=us-east1-b
docker exec ollama ollama pull gemma4:31b
```

### Backup to GCS (optional)

```bash
# On the VM — copy model weights to the GCS bucket for safe-keeping
gsutil -m cp -r /opt/ollama-models/models/gemma4 \
  gs://amos-taskorbit-ollama-models/
```

### Add to the UI dropdown

Open `frontend/src/lib/pipelineOptions.ts` and append the tag to the `ollama` array:

```typescript
ollama: [
  "gemma4:26b",
  "gemma4:e4b",
  "qwen3.6:27b",
  "qwen3.5:9b",
  "gemma4:31b",   // ← add here
],
```

No backend change needed.

---

## 5 — Remove a Model

```bash
gcloud compute ssh taskorbit-ollama-inference --zone=us-east1-b
docker exec ollama ollama rm gemma4:e4b
```

To also free up GCS backup storage:

```bash
gsutil rm -r gs://amos-taskorbit-ollama-models/gemma4/
```

---

## 6 — Update Ollama to a New Version

Pin the version in `terraform.tfvars`:

```hcl
ollama_version = "0.7.0"
```

Then re-apply. Terraform recreates the VM instance, which re-runs the startup script with the new Ollama version. **Models on the local SSD are lost** — you must re-pull them after the new VM starts.

To preserve models across version upgrades, back them up to GCS first:

```bash
gsutil -m cp -r /opt/ollama-models/ gs://amos-taskorbit-ollama-models/
```

---

## 7 — Selecting Ollama in the UI

1. Open the **Agent Configuration** page
2. Go to the **Pipeline** tab
3. Set **LLM Provider** → `Ollama (self-hosted)`
4. Choose a model from the **Model** dropdown (`gemma4:26b` is the default)
5. Save the agent

The agent now routes all LLM calls through the self-hosted GCE VM.

---

## 8 — Validate a Running Instance

```bash
VM_IP="35.231.129.211"  # replace with your static IP

# List loaded models
curl http://$VM_IP:11434/api/tags | jq '.models[].name'

# Test a completion (native API, think=false)
curl -X POST http://$VM_IP:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{"model":"gemma4:26b","think":false,"stream":false,"messages":[{"role":"user","content":"Say hello"}]}'
```

To verify requests are reaching the self-hosted endpoint via the backend, check logs:

```bash
gcloud logging read \
  'jsonPayload.event="llm_client_selected" AND jsonPayload.provider="ollama"' \
  --project=amos-taskorbit --limit=5 --format=json
```

Or in Grafana (Loki):

```logql
{job="cloud-run-logs"} |= "llm_client_selected" | json | provider = "ollama"
```

---

## Cost Reference

| Scenario | Hourly cost | Weekly cost (estimate) |
|---|---|---|
| g2-standard-8 + NVIDIA L4, 24/7 | ~$1.30/h | ~$218 |
| Work hours only (Mon–Fri 08–22) | ~$1.30/h | ~$91 |
| VM stopped (idle) | $0 | $0 |

GCS model storage: ~$0.02/GB/month (negligible for 48 GB of model weights).

---

## Troubleshooting

**Port 11434 unreachable from backend**
Check the firewall rule exists and the VM has the `taskorbit-ollama` network tag:
```bash
gcloud compute firewall-rules describe taskorbit-ollama-api --project=amos-taskorbit
gcloud compute instances describe taskorbit-ollama-inference \
  --zone=us-east1-b --format="value(tags.items)"
```

**`/api/tags` returns empty model list**
Models have not been pulled yet. SSH into the VM and run `docker exec ollama ollama pull gemma4:26b`.

**Inference request times out**
The `OllamaClient` uses a 300 s timeout. If you see consistent timeouts on the first request after a restart, the model is still loading into VRAM (~10–15 s). Retry once.

**`content` field is empty, `reasoning` contains text**
The model is in thinking mode. Verify `OllamaClient` is sending `"think": false` at the top level of the `/api/chat` request body (not inside `options`). The OpenAI-compatible `/v1/chat/completions` endpoint does **not** forward this flag — always use `/api/chat`.

**`intent_router_parse_error` in backend logs**
The intent router could not extract valid JSON from the LLM response. This typically means the model returned preamble text before the JSON object. The router uses `re.search(r"\{[^{}]*\}", raw)` to extract the first JSON block — if the response format is unusual, check the raw LLM output in logs.

**`OLLAMA_BASE_URL not set` error**
Set `OLLAMA_BASE_URL=http://<static-ip>:11434` in `backend/.env` (local) or in the `ollama-base-url` Secret Manager secret (Cloud Run).

**VM startup script did not complete**
Check serial console output:
```bash
gcloud compute instances get-serial-port-output taskorbit-ollama-inference \
  --zone=us-east1-b --project=amos-taskorbit | tail -50
```
