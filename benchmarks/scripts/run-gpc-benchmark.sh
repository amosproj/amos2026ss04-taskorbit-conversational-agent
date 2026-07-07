#!/usr/bin/env bash
# Standardized component benchmark run for GPC (#68).
# Usage (on GPC):
#   export BENCHMARK_API_URL=http://localhost:8000
#   export BENCHMARK_API_TOKEN=<jwt>
#   export DEEPGRAM_API_KEY=<key>
#   export ELEVENLABS_API_KEY=<key>
#   ./benchmarks/scripts/run-gpc-benchmark.sh
# Optional:
#   export BENCHMARK_CONFIG=benchmarks/configs/component-benchmark.yaml

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAMP="$(date +%Y%m%dT%H%M%S)"
RESULTS_DIR="${RESULTS_DIR:-$REPO_ROOT/benchmarks/results/gpc-$STAMP}"
BENCHMARK_CONFIG="${BENCHMARK_CONFIG:-benchmarks/configs/component-benchmark-oss-only.yaml}"

cd "$REPO_ROOT"
export PYTHONPATH=benchmarks/runner

echo "==> Results dir: $RESULTS_DIR"
echo "==> Config: $BENCHMARK_CONFIG"
python3 benchmarks/runner/run_component_benchmark.py \
  --config "$BENCHMARK_CONFIG" \
  --results-dir "$RESULTS_DIR/component"

python3 benchmarks/runner/aggregate.py \
  --results-dir "$RESULTS_DIR" \
  --report \
  --write-report "$RESULTS_DIR/component-benchmark-report.txt"

echo "==> Done. JSONL in $RESULTS_DIR/component/"
echo "==> Report: $RESULTS_DIR/component-benchmark-report.txt"
