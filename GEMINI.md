# TaskOrbit Conversational Agent: Team Mandates

This file contains foundational mandates for the TaskOrbit project. Adherence is mandatory for all contributors (human and AI).

## 1. Release Management
- **Pre-Release Prep:** A Release Candidate (RC) tag MUST be created and verified on the `main` branch prior to any Sprint Release meeting.
- **Decision Focus:** Release meetings are for final Go/No-Go decisions on the RC. Avoid line-by-line changelog reviews during the meeting.

## 2. Quality & Bug Reporting
- **Dev-Led Reporting:** Developers are explicitly mandated to open bug reports as soon as issues are discovered. Do not wait for Product Owners to identify or report them.
- **Automated Verification:** All code changes must be accompanied by relevant unit or integration tests. Verification is not complete without automated tests.

## 3. Configuration & Infrastructure
- **Atomic PRs:** Any code change introducing or modifying environment variables MUST include the corresponding Terraform updates in the same Pull Request.
- **Schema Compliance:** All modifications to the agent or task models MUST be validated against `schemas/agent-task.schema.json`.

## 4. Interaction & Demos
- **Audio Verification:** Always verify system audio sharing functionality before any scheduled demo or review session.

## 5. Database & Seeding
- **Seed Defaults:** To re-insert missing default agent templates and the dummy dev user, run the following command from the `backend` directory: `poetry run python scripts/seed_defaults.py`. This script is safe to run multiple times.

## 6. Version Control
- **Local Documentation:** Never commit local markdown files (`HANDOFF_49_DHRUVIN.md`, `LOCAL_AMOS_DELIVERABLES.md`, `LOCAL_NOTES.md`, `TASK_49_DHRUVIN_FRONTEND.md`, `TASK_49_SHIKHAR_BACKEND.md`, `TEST_PLAN_49.md`, `RELEASE_CONTEXT.md`, `SPRINT_07_RELEASE_DRAFT.md`) to the repository. These are for local reference only.
