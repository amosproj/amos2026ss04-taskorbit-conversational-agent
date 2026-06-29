# ── Service Account ───────────────────────────────────────────────────────────

resource "google_service_account" "ollama_sa" {
  count        = var.enable_gpu_inference ? 1 : 0
  account_id   = "taskorbit-ollama-sa"
  display_name = "TaskOrbit Ollama Inference SA"
  project      = var.project_id
}

resource "google_project_iam_member" "ollama_sa_roles" {
  for_each = var.enable_gpu_inference ? toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/secretmanager.secretAccessor",
  ]) : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.ollama_sa[0].email}"
}

# ── GCS bucket for persistent model storage ───────────────────────────────────
#
# The GCS bucket serves as persistent backup for model weights.
# Models are pulled on first use via `docker exec ollama ollama pull <model>`
# and stored on the VM's local SSD at /opt/ollama-models.
# To pre-populate: gsutil cp -r gs://<project_id>-ollama-models/ /opt/ollama-models/

resource "google_storage_bucket" "ollama_models" {
  count    = var.enable_gpu_inference ? 1 : 0
  name     = "${var.project_id}-ollama-models"
  location = var.bucket_location  # independent of GPU inference region so region changes don't recreate the bucket
  project  = var.project_id

  uniform_bucket_level_access = true

  # Hierarchical namespace speeds up large LLM file access patterns
  hierarchical_namespace { enabled = true }

  lifecycle {
    prevent_destroy = true  # bucket holds 48+ GiB of model weights — never auto-delete
  }
}

resource "google_storage_bucket_iam_member" "ollama_sa_gcs" {
  count  = var.enable_gpu_inference ? 1 : 0
  bucket = google_storage_bucket.ollama_models[0].name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.ollama_sa[0].email}"
}

# ── GCE VM GPU instance ────────────────────────────────────────────────────────
#
# Uses a GCP Deep Learning VM image which ships with NVIDIA driver 550+ and
# CUDA 12.4 pre-installed — no reboot or driver install needed in the startup
# script. Cloud Run GPU nodes are locked to NVIDIA driver 535 which is too old
# for Ollama 0.30+ (requires driver 550+), so a GCE VM is used instead.
#
# Machine: g2-standard-8 (8 vCPU, 32 GB RAM) + 1x NVIDIA L4 GPU.
# Models are read from the GCS bucket via gcsfuse at /models.

resource "google_compute_address" "ollama_ip" {
  count   = var.enable_gpu_inference ? 1 : 0
  name    = "taskorbit-ollama-ip"
  region  = var.region
  project = var.project_id
}

resource "google_compute_firewall" "ollama_api" {
  count   = var.enable_gpu_inference ? 1 : 0
  name    = "taskorbit-ollama-api"
  network = "default"
  project = var.project_id

  allow {
    protocol = "tcp"
    ports    = ["11434"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["taskorbit-ollama"]
}

resource "google_compute_instance" "ollama" {
  count        = var.enable_gpu_inference ? 1 : 0
  name         = "taskorbit-ollama-inference"
  machine_type = "g2-standard-8"
  zone         = var.zone
  project      = var.project_id

  tags = ["taskorbit-ollama"]

  boot_disk {
    initialize_params {
      # Deep Learning VM image — NVIDIA driver 580 and CUDA 12.9 pre-installed.
      # Docker and nvidia-container-toolkit are also included.
      image = "projects/deeplearning-platform-release/global/images/family/common-cu129-ubuntu-2204-nvidia-580"
      size  = 100
      type  = "pd-ssd"
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.ollama_ip[0].address
    }
  }

  scheduling {
    on_host_maintenance = "TERMINATE"  # required for GPU instances
    automatic_restart   = true
    preemptible         = var.preemptible
  }

  guest_accelerator {
    type  = "nvidia-l4"
    count = 1
  }

  service_account {
    email  = google_service_account.ollama_sa[0].email
    scopes = ["cloud-platform"]
  }

  metadata = {
    # install-nvidia-driver = "True" is a GCP metadata flag recognized by the
    # deep learning image to verify the driver on first boot.
    install-nvidia-driver = "True"

    startup-script = <<-SCRIPT
      #!/bin/bash
      set -euo pipefail

      # Wait for NVIDIA driver (deep learning image installs on first boot)
      for i in $(seq 1 30); do
        nvidia-smi &>/dev/null && break || sleep 10
      done

      # Install Docker if not present (not included in all DL VM images)
      if ! command -v docker &>/dev/null; then
        curl -fsSL https://get.docker.com | sh
      fi

      # Install nvidia-container-toolkit for Docker GPU support
      if ! dpkg -l nvidia-container-toolkit &>/dev/null 2>&1; then
        distribution=$(. /etc/os-release; echo $ID$VERSION_ID)
        curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
          | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
        curl -s -L "https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list" \
          | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
          | tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
        apt-get update -y && apt-get install -y nvidia-container-toolkit
        nvidia-ctk runtime configure --runtime=docker
        systemctl restart docker
      fi

      # Run Ollama — models are pulled on first use and stored in /opt/ollama-models
      mkdir -p /opt/ollama-models
      if ! docker ps --filter name=ollama --filter status=running | grep -q ollama; then
        docker rm -f ollama 2>/dev/null || true
        docker run -d \
          --name ollama \
          --gpus all \
          --restart unless-stopped \
          -p 11434:11434 \
          -v /opt/ollama-models:/root/.ollama \
          -e OLLAMA_HOST=0.0.0.0:11434 \
          -e OLLAMA_KEEP_ALIVE=-1 \
          -e OLLAMA_NUM_PARALLEL=4 \
          ollama/ollama:${var.ollama_version}
      fi
    SCRIPT
  }
}
