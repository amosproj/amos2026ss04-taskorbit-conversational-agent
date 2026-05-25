# Remote state — GCS bucket must be created manually before the first `terraform init`.
# Create it once with: gsutil mb -l REGION gs://YOUR_PROJECT_ID-taskorbit-tf-state
# export GOOGLE_APPLICATION_CREDENTIALS="./amos-taskorbit.json"
terraform {
  backend "gcs" {
    bucket = "amos-taskorbit-tf-state"
    prefix = "terraform/state"
  }
}
