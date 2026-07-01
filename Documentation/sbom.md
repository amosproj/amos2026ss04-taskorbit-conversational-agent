# SBOM & Legal Notices

This document describes how the TaskOrbit monorepo generates, verifies, and
publishes its Software Bill of Materials (SBOM) and Legal Notices for
third-party dependencies.

## Purpose

- Issue [#138](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/138):
  automate SBOM generation and display third-party licenses in the app UI.
- **Compliance:** tracks every open-source dependency shipped in the
  application Docker images.

## Scope

| Layer | Included | Method |
|-------|----------|--------|
| Backend (Python / Poetry) | Yes | `syft scan dir:backend` |
| Frontend (npm / React) | Yes | `syft scan dir:frontend` |
| Infrastructure (Terraform) | **No** | Separate Syft per `terraform/README.md` |

Terraform provider dependencies are documented separately and **not** shown in
the in-app Legal Notices UI.

## Tool: Syft

[Syft](https://github.com/anchore/syft) generates the CycloneDX JSON v1.5 SBOM
from lockfiles (`poetry.lock`, `package-lock.json`).

- No SaaS account needed.
- Runs locally and in CI.
- Uses **stdlib only** for extraction — no runtime dependencies.

## Regenerate

```bash
./scripts/generate-sbom.sh
```

This will:

1. Scan `backend/` and `frontend/` with Syft
2. Merge both scans into `Documentation/sbom.cyclonedx.json`
3. Extract license data into `frontend/src/generated/legal-notices.json`

### When to regenerate

After any change to:

- `backend/poetry.lock` (new / updated Python package)
- `frontend/package-lock.json` (new / updated npm package)

## Artifacts

| Path | Type | Committed | Purpose |
|------|------|-----------|---------|
| `Documentation/sbom.cyclonedx.json` | CycloneDX JSON 1.5 | Yes | Full SBOM |
| `frontend/src/generated/legal-notices.json` | Custom JSON | Yes | UI data |

Both files are **committed to git**. CI verifies they are up to date with the
lockfiles on every push (see below).

## CI verification

Workflow: `.github/workflows/verify-sbom.yml`

Triggers on every push / PR:

1. Install Syft
2. Re-run `./scripts/generate-sbom.sh`
3. `git diff --exit-code` against the committed artifacts

If the workflow fails, run `./scripts/generate-sbom.sh` locally and commit the
updated artifacts.

## Sprint planning

Sprint deliverables (`Deliverables/sprint-*/planning-documents.xlsx` / `.pdf`)
should be updated manually with the SBOM metadata. The current values can be
found in `frontend/src/generated/legal-notices.json`:

- **Component count:** `componentCount`
- **Last generated:** `generatedAt`

## Related

- [Implementation plan](issue-138-sbom-legal-notices-plan.md) — full design
  decisions and architecture
- [Issue #138](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/138)
