#!/usr/bin/env bash
# Local component benchmark demo — loads keys from backend/.env (not printed).
#
# Real results (non-dry-run) need the TaskOrbit backend running:
#   cd backend && poetry run uvicorn taskorbit.api.main:app --reload
#
# Usage:
#   ./benchmarks/scripts/run-local-demo.sh dry-run
#   ./benchmarks/scripts/run-local-demo.sh text
#   ./benchmarks/scripts/run-local-demo.sh voice
#   ./benchmarks/scripts/run-local-demo.sh text+voice

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ENV_FILE="$REPO_ROOT/backend/.env"
MODE="${1:-text}"
STAMP="$(date +%Y%m%dT%H%M%S)"
RESULTS_DIR="$REPO_ROOT/benchmarks/results/demo-$STAMP"

# Load backend/.env into this shell (keys stay private — not echoed).
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  echo "==> Loaded env from backend/.env"
else
  echo "WARN: backend/.env not found — voice keys may be missing" >&2
fi

export BENCHMARK_API_URL="${BENCHMARK_API_URL:-http://localhost:8000}"
export PYTHONPATH="$REPO_ROOT/benchmarks/runner"

# Voice harness reads these from the shell (not from backend/.env at runtime).
export DEEPGRAM_API_KEY="${DEEPGRAM_API_KEY:-}"
export ELEVENLABS_API_KEY="${ELEVENLABS_API_KEY:-}"

echo "==> BENCHMARK_API_URL=$BENCHMARK_API_URL"
if [[ -n "${DEEPGRAM_API_KEY:-}" ]]; then echo "==> DEEPGRAM_API_KEY: set"; else echo "==> DEEPGRAM_API_KEY: missing"; fi
if [[ -n "${ELEVENLABS_API_KEY:-}" ]]; then echo "==> ELEVENLABS_API_KEY: set"; else echo "==> ELEVENLABS_API_KEY: missing"; fi
if [[ -n "${OPENAI_API_KEY:-}" ]]; then echo "==> OPENAI_API_KEY: set"; else echo "==> OPENAI_API_KEY: missing"; fi
echo "==> OLLAMA_BASE_URL: ${OLLAMA_BASE_URL:-missing}"

CONFIG="$REPO_ROOT/benchmarks/configs/component-benchmark-smoke.yaml"
COMPONENT_DIR="$RESULTS_DIR/component"
mkdir -p "$COMPONENT_DIR"
ARGS=(--config "$CONFIG" --results-dir "$COMPONENT_DIR")

case "$MODE" in
  dry-run)
    echo "==> Dry run (no backend required)"
    python3 "$REPO_ROOT/benchmarks/runner/run_component_benchmark.py" "${ARGS[@]}" --dry-run
    ;;
  text)
    echo "==> Live text benchmark (backend required at $BENCHMARK_API_URL)"
    echo "==> OSS config: Ollama VRAM warmup + 30s buffer before timed runs (see logs)"
    curl -sf "$BENCHMARK_API_URL/health" >/dev/null || {
      echo "ERROR: Backend not reachable. Start it first:" >&2
      echo "  cd backend && poetry run uvicorn taskorbit.api.main:app --reload" >&2
      exit 1
    }
    python3 "$REPO_ROOT/benchmarks/runner/run_component_benchmark.py" "${ARGS[@]}" --paths text
    ;;
  voice)
    echo "==> Live voice benchmark (backend + DEEPGRAM_API_KEY required)"
    echo "==> OSS config: Ollama VRAM warmup + 30s buffer before timed runs (see logs)"
    curl -sf "$BENCHMARK_API_URL/health" >/dev/null || {
      echo "ERROR: Backend not reachable. Start it first." >&2
      exit 1
    }
    python3 "$REPO_ROOT/benchmarks/runner/run_component_benchmark.py" "${ARGS[@]}" --paths voice
    ;;
  text+voice|all)
    echo "==> Live text + voice benchmark"
    curl -sf "$BENCHMARK_API_URL/health" >/dev/null || {
      echo "ERROR: Backend not reachable. Start it first." >&2
      exit 1
    }
    python3 "$REPO_ROOT/benchmarks/runner/run_component_benchmark.py" "${ARGS[@]}"
    ;;
  *)
    echo "Usage: $0 {dry-run|text|voice|text+voice}" >&2
    exit 1
    ;;
esac

echo "==> Aggregating results..."
python3 "$REPO_ROOT/benchmarks/runner/aggregate.py" \
  --results-dir "$RESULTS_DIR" \
  --report \
  --write-report "$RESULTS_DIR/component-benchmark-report.txt"

echo ""
echo "==> Done."
echo "    JSONL:   $RESULTS_DIR/component/"
echo "    Report:  $RESULTS_DIR/component-benchmark-report.txt"
echo "    Excel:   $RESULTS_DIR/benchmark-summary.csv  (Overall + By category — open for PO demo)"
echo ""
cat "$RESULTS_DIR/component-benchmark-report.txt"
