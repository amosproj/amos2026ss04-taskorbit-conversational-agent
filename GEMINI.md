# Project Conventions & Workflows

## Branching Strategy
- **Feature Branches**: All development happens in feature branches.
- **`main` Branch**: Feature branches are merged into `main`. `main` serves as the integration and testing ground.
- **`prod` Branch**: Used for production deployments.

## Deployment Workflow
- **Production Deployment**: Once changes are tested and confirmed working on `main`, a Merge Request (MR) is created from `main` to `prod`.
- **Automatic Deployment**: Pushing to `prod` (via MR) automatically triggers the CI/CD pipeline (build, push images, deploy to Cloud Run).
- **No Direct Pushes**: Never push directly to the `prod` branch.
- **Verification**: Only create the `main` -> `prod` MR when the team has confirmed everything works on `main`.

## Environment Variables & Infrastructure
- **Terraform Updates**: If an environment variable is added or updated in the code, the corresponding Terraform configuration must be updated in the same PR.
- **Checklist for New/Updated Env Vars**:
  1.  **`backend/.env.example`**: Add the key with a placeholder value.
  2.  **`terraform/modules/secrets/main.tf`**: Create a Secret Manager secret for sensitive values (API keys, passwords).
  3.  **`terraform/modules/cloud_run/main.tf`**: Mount the secret/variable on the Cloud Run service (backend, worker, or both).
  4.  **`terraform/variables.tf` + `terraform/terraform.tfvars.example`**: Update if the value differs per environment.
  5.  **`backend/src/taskorbit/config.py`**: Add the variable to the `Settings` class.
