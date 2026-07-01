#!/usr/bin/env bash
# ------------------------------------------------------------------
# generate-sbom.sh — SBOM generation and legal notices extraction.
#
# Orchestrates:
#   1. Syft scan of backend (Poetry) + frontend (npm)
#   2. Write combined CycloneDX JSON to Documentation/sbom.cyclonedx.json
#   3. Run extract_legal_notices.py to produce frontend/src/generated/legal-notices.json
#
# Prerequisites:
#   - syft installed on PATH  (https://github.com/anchore/syft)
#   - python3 available (stdlib only for extraction)
#
# Usage:
#   ./scripts/generate-sbom.sh
# ------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Preflight ──────────────────────────────────────────────────────────

if ! command -v syft &>/dev/null; then
  echo "ERROR: 'syft' not found on PATH. Install it first:"
  echo "  brew install syft         # macOS"
  echo "  or see https://github.com/anchore/syft"
  exit 1
fi

# ── Scan ───────────────────────────────────────────────────────────────

echo "==> Scanning backend (Poetry) with Syft ..."

syft scan "dir:$REPO_ROOT/backend" \
  --exclude './**/__pycache__/**' \
  --exclude './**/.venv/**' \
  --exclude './**/tests/**' \
  -o cyclonedx-json@1.5 \
  -q > "/tmp/sbom-backend.json"

echo "   -> backend scan complete ($(python3 -c "import json; print(len(json.load(open('/tmp/sbom-backend.json'))['components']))") components)"

echo "==> Scanning frontend (npm) with Syft ..."

syft scan "dir:$REPO_ROOT/frontend" \
  --exclude './node_modules/**' \
  --exclude './dist/**' \
  -o cyclonedx-json@1.5 \
  -q > "/tmp/sbom-frontend.json"

echo "   -> frontend scan complete ($(python3 -c "import json; print(len(json.load(open('/tmp/sbom-frontend.json'))['components']))") components)"

echo "==> Merging scans into combined CycloneDX BOM ..."

python3 -c "
import json

with open('/tmp/sbom-backend.json') as f:
    be = json.load(f)
with open('/tmp/sbom-frontend.json') as f:
    fe = json.load(f)

merged = dict(be)
merged['components'] = (be.get('components', []) + fe.get('components', []))
merged['metadata']['component']['name'] = 'taskorbit-conversational-agent'
merged['metadata']['component']['description'] = 'TaskOrbit Conversational Agent (backend + frontend)'
print(json.dumps(merged, indent=2))
" > "$REPO_ROOT/Documentation/sbom.cyclonedx.json"

echo "   -> Documentation/sbom.cyclonedx.json written ($(python3 -c "import json; print(len(json.load(open('$REPO_ROOT/Documentation/sbom.cyclonedx.json'))['components']))") components)"

# ── Extract legal notices ──────────────────────────────────────────────

echo "==> Extracting legal notices for UI ..."

python3 "$SCRIPT_DIR/extract_legal_notices.py" \
  --input "$REPO_ROOT/Documentation/sbom.cyclonedx.json" \
  --output "$REPO_ROOT/frontend/src/generated/legal-notices.json"

echo "   -> frontend/src/generated/legal-notices.json written"

# ── Summary ────────────────────────────────────────────────────────────

COMPONENT_COUNT=$(python3 -c "
import json, sys
with open('$REPO_ROOT/Documentation/sbom.cyclonedx.json') as f:
    bom = json.load(f)
print(len(bom.get('components', [])))
")
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo ""
echo "✔ SBOM regeneration complete"
echo "  Components : $COMPONENT_COUNT"
echo "  Timestamp  : $TIMESTAMP"
