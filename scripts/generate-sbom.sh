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
# NOTE: metadata.timestamp is derived from lockfile git history (not Syft scan time)
# so CI and local regen stay in sync. serialNumber is a sha256 of the component payload.

python3 -c "
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone

repo_root = '$REPO_ROOT'

with open('/tmp/sbom-backend.json') as f:
    be = json.load(f)
with open('/tmp/sbom-frontend.json') as f:
    fe = json.load(f)

merged = dict(be)
components = be.get('components', []) + fe.get('components', [])

def drop_syft_lockfile_entries(items):
    kept = []
    for comp in items:
        purl = comp.get('purl') or ''
        if purl.startswith('pkg:'):
            kept.append(comp)
            continue
        name = os.path.basename(comp.get('name', ''))
        if name in {'poetry.lock', 'package-lock.json'}:
            continue
        kept.append(comp)
    return kept

components = drop_syft_lockfile_entries(components)
merged['components'] = components
merged['metadata']['component'] = {
    'type': 'application',
    'name': 'taskorbit-conversational-agent',
    'description': 'TaskOrbit Conversational Agent (backend + frontend)',
}

def lockfile_timestamp(repo_root):
    rel_paths = ['backend/poetry.lock', 'frontend/package-lock.json']
    timestamps = []
    for rel in rel_paths:
        if not os.path.exists(os.path.join(repo_root, rel)):
            continue
        try:
            stamp = subprocess.check_output(
                ['git', 'log', '-1', '--format=%cI', '--', rel],
                cwd=repo_root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            stamp = ''
        if not stamp:
            continue
        if stamp.endswith('Z'):
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        else:
            parsed = datetime.fromisoformat(stamp)
        timestamps.append(parsed)
    if timestamps:
        return max(timestamps).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    lock_paths = [os.path.join(repo_root, rel) for rel in rel_paths]
    lock_mtimes = [os.path.getmtime(path) for path in lock_paths if os.path.exists(path)]
    if lock_mtimes:
        return datetime.fromtimestamp(max(lock_mtimes), tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    return datetime.fromtimestamp(0, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

merged['metadata']['timestamp'] = lockfile_timestamp(repo_root)

payload = json.dumps(components, sort_keys=True, separators=(',', ':')).encode('utf-8')
digest = hashlib.sha256(payload).hexdigest()
merged['serialNumber'] = (
    f'urn:uuid:{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}'
)

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
