# SBOM & Legal Notices — Testing Guide

How to verify the SBOM automation and Legal Notices UI after implementation.

---

## 1. Regenerate artifacts

```bash
./scripts/generate-sbom.sh
```

Expect:
- `Documentation/sbom.cyclonedx.json` — valid JSON, contains a `components` array
- `frontend/src/generated/legal-notices.json` — has `generatedAt`, `componentCount`, and a list of components

Check:
```bash
python3 -c "import json; d=json.load(open('Documentation/sbom.cyclonedx.json')); print(f'SBOM: {len(d[\"components\"])} components')"
python3 -c "import json; d=json.load(open('frontend/src/generated/legal-notices.json')); print(f'Legal: {d[\"componentCount\"]} components, generated {d[\"generatedAt\"]}')"
```

Spot-check known packages:
```bash
python3 -c "
import json
d = json.load(open('frontend/src/generated/legal-notices.json'))
names = {c['name'] for c in d['components']}
for pkg in ['fastapi', 'react', 'livekit-client', 'sqlalchemy', 'tailwind-merge']:
    print(f'  {pkg}: {\"✓\" if pkg in names else \"✗ MISSING\"}')
"
```

---

## 2. Unit tests

```bash
cd backend && poetry run pytest tests/test_extract_legal_notices.py -v
```

8 tests covering:
| Test | What it checks |
|------|---------------|
| `test_extracts_spdx_license_id` | SPDX `id` is preferred |
| `test_falls_back_to_license_name` | Falls back to `name` when no `id` |
| `test_unknown_when_no_license` | Missing license → `UNKNOWN` |
| `test_dedupes_components` | Duplicate ecosystem+name+version are collapsed |
| `test_sorts_alphabetically` | Sorted by ecosystem, name, version |
| `test_skips_non_package_components` | Non-`pkg:` purls excluded |
| `test_output_schema` | Required top-level fields present |
| `test_component_count_matches` | `componentCount` matches array length |

All should pass.

---

## 3. Backend CI checks

```bash
cd backend && poetry run ruff check . && poetry run ruff format --check . && poetry run pytest
```

Expect: clean lint, clean format check, all tests pass (674 passed, 13 skipped expected).

---

## 4. Frontend CI checks

```bash
cd frontend && npm run lint && npm run build
```

- Lint: 0 errors (pre-existing warnings acceptable)
- Build: `tsc -b` succeeds, `vite build` produces `dist/`

---

## 5. Manual UI smoke test

```bash
cd frontend && npm run dev
```

Open http://localhost:5173 and verify:

| Step | Expected |
|------|----------|
| Footer is visible at page bottom | "Legal Notices" link + "© 2026 TaskOrbit" |
| Click "Legal Notices" | Dialog opens with title "Legal Notices" |
| Dialog shows component count | "X of Y" counter visible |
| Type in search box | Filter narrows results |
| Search "MIT" | Only MIT-licensed packages shown |
| Search "UNKNOWN" | Packages with unknown licenses appear |
| Scroll list | Scrollbar works, table headers stay visible |
| Close dialog | Click X or press Escape |
| Dark mode | Toggle theme — dialog still readable |
| Responsive | Narrow viewport — dialog adapts |

---

## 6. Test unknown-license handling

Find packages with unknown licenses:
```bash
python3 -c "
import json
d = json.load(open('frontend/src/generated/legal-notices.json'))
unknown = [c for c in d['components'] if c['license'] == 'UNKNOWN']
print(f'{len(unknown)} packages with UNKNOWN license:')
for c in unknown[:10]:
    print(f'  {c[\"name\"]} ({c[\"ecosystem\"]})')
if len(unknown) > 10:
    print(f'  ... and {len(unknown)-10} more')
```

In the UI, search "UNKNOWN" — these packages should appear with italic/muted license text and a tooltip on hover.

---

## 7. Test CI workflow (dry run)

The CI workflow is at `.github/workflows/verify-sbom.yml`. To test it locally:

```bash
# Simulate stale artifacts
echo " " >> Documentation/sbom.cyclonedx.json
./scripts/generate-sbom.sh
git diff --exit-code Documentation/sbom.cyclonedx.json frontend/src/generated/legal-notices.json
```

The `git diff` should exit 0 (no diff). Now simulate a drift:

```bash
# Commit current artifacts, change a lockfile, then check CI behaviour
# The workflow will regenerate and diff — if diff is non-empty it fails.
```

---

## 8. Regeneration after dependency change

```bash
# Add a test dependency
cd backend && poetry add cowsay && cd ..
./scripts/generate-sbom.sh
```

Check that `cowsay` appears in `legal-notices.json`:
```bash
python3 -c "
import json
d = json.load(open('frontend/src/generated/legal-notices.json'))
found = [c for c in d['components'] if 'cowsay' in c['name']]
print(f'cowsay: {found[0][\"license\"] if found else \"NOT FOUND\"}')"
```

Roll back:
```bash
cd backend && poetry remove cowsay && cd ..
```

---

## 9. Edge cases

| Scenario | How to test | Expected |
|----------|-------------|----------|
| Empty lockfile | Remove all deps from a lockfile, regen | 0-component notice |
| Missing Syft | Run script without Syft installed | Clear error message |
| Corrupt CycloneDX | Edit JSON, re-run extract | Script exits non-zero |
| Large SBOM (>1 MB) | Check file size with `wc -c` | Pre-commit allows it (excluded) |
| Generated files gitignored | Check `.gitignore` for patterns matching our files | No exclusion |

---

## 10. Full pre-PR checklist

```bash
./scripts/generate-sbom.sh
cd backend && poetry run pytest tests/test_extract_legal_notices.py -v && poetry run ruff check . && poetry run ruff format --check . && poetry run pytest && cd ..
cd frontend && npm run lint && npm run build && cd ..
git status
```
