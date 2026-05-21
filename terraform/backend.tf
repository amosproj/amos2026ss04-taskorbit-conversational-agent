# Remote state — GCS bucket must be created manually before the first `terraform init`.
# Create it once with: gsutil mb -l REGION gs://YOUR_PROJECT_ID-taskorbit-tf-state
terraform {
  backend "gcs" {
    bucket = "REPLACE_WITH_PROJECT_ID-taskorbit-tf-state"
    prefix = "terraform/state"
  }
}
