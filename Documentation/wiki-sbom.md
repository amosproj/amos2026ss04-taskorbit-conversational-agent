# SBOM & Legal Notices

**Issue:** [#138 SBOM Automation & Legal Notices UI](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/138)

---

## User story

> As a developer  
> I want the application to automatically generate an SBOM and display the third-party licenses as Legal Notices in the UI  
> So that I can view the open-source licenses and legal credits of the libraries used in the application

---

## Overview

TaskOrbit uses [Syft](https://github.com/anchore/syft) to scan all application dependencies and publish them in two places:

1. **Machine-readable SBOM** — `Documentation/sbom.cyclonedx.json` (CycloneDX JSON 1.5)
2. **In-app Legal Notices** — searchable dialog in the application footer

Every open-source package in the backend and frontend is inventoried. Licenses are displayed automatically — SPDX IDs where available, `UNKNOWN` where metadata is missing (blind accept: nothing is hidden).

---

## Implementation status

| Area | Status |
|------|--------|
| Syft SBOM generation (`scripts/generate-sbom.sh`) | ✅ Done |
| CycloneDX artifact (`Documentation/sbom.cyclonedx.json`) | ✅ Done — 247 components |
| License extraction (`scripts/extract_legal_notices.py`) | ✅ Done |
| Legal Notices UI (footer dialog) | ✅ Done — 245 components shown |
| Unit tests (`test_extract_legal_notices.py`) | ✅ Done — 8/8 passing |
| CI verification (`.github/workflows/verify-sbom.yml`) | ✅ Done |
| Sprint planning BOM (`Deliverables/sprint-12/`) | ✅ Done |

---

## How it works

### Developer workflow

```bash
# Prerequisites: brew install syft
./scripts/generate-sbom.sh
```

The script:

1. Scans `backend/` with Syft (Poetry packages)
2. Scans `frontend/` with Syft (npm packages)
3. Merges both into `Documentation/sbom.cyclonedx.json`
4. Extracts `frontend/src/generated/legal-notices.json` for the UI

Run after any change to `backend/poetry.lock` or `frontend/package-lock.json`, then commit both generated files with the lockfile change.

### In the application

The frontend bundles `legal-notices.json` at build time. Users click **Legal Notices** in the footer to search packages, filter by license, and view component counts.

---

## CI/CD integration

SBOM verification is part of the project's CI pipeline.

| Workflow | Triggers | What it does |
|----------|----------|--------------|
| `verify-sbom.yml` | Every push + every PR | Regenerates SBOM artifacts and confirms they match what is committed |
| `deploy.yml` | After quality gates on `prod` | Frontend image includes the committed `legal-notices.json` |

This keeps the SBOM in sync with lockfiles automatically — if a developer updates dependencies without regenerating, CI catches it before merge.

---

## Scope

| Layer | Included |
|-------|----------|
| Backend (Python / Poetry) | ✅ |
| Frontend (npm / React) | ✅ |
| Terraform providers | Documented separately in `terraform/README.md` |

---

## Artifacts

| File | Purpose |
|------|---------|
| `Documentation/sbom.cyclonedx.json` | Full CycloneDX JSON 1.5 SBOM |
| `frontend/src/generated/legal-notices.json` | License list for the UI |
| `Deliverables/sprint-12/planning-documents.xlsx` | Sprint Bill of Materials |

**Current scan:**

- **SBOM components:** 247
- **Legal notices (UI):** 245
- **Last generated:** `2026-07-02T06:42:43Z`

---

## Verification

```bash
./scripts/generate-sbom.sh
cd backend && poetry run pytest tests/test_extract_legal_notices.py -v
cd frontend && npm run dev   # → footer "Legal Notices"
```

---

## Acceptance criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | SCA tool generates up-to-date SBOM | ✅ Syft → `sbom.cyclonedx.json` |
| 2 | Dependencies scanned with blind accept | ✅ All listed; unknown → `UNKNOWN` |
| 3 | Planning Documents SBOM updated | ✅ Sprint 12 Bill of Materials |
| 4 | Legal Notices section/modal in UI | ✅ Footer link + dialog |
| 5 | UI renders auto-generated license info | ✅ Imports `legal-notices.json` |

---

## Related

- [`Documentation/sbom.md`](sbom.md) — operational guide
- [`Documentation/sbom-testing-guide.md`](sbom-testing-guide.md) — testing checklist
- [Syft documentation](https://github.com/anchore/syft)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-02 | Wiki page published; Sprint 12 BOM updated; end-to-end automation verified |
| 2026-07-01 | SBOM generation + Legal Notices UI shipped (#138) |
