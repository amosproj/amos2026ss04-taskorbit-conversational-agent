# TaskOrbit Benchmarking Environment

A standardized, reproducible benchmarking framework for TaskOrbit conversational agent experiments. Execute experiments, collect consistent metrics, persist results, and compare runs.

## Quick Start

### Setup

```bash
cd benchmarks
pip install -r requirements.txt
```

### Run an Experiment

```bash
python runner/run_benchmark.py --config configs/baseline-cloud.yaml
```

### Component Benchmarks (#68)

Compare STT / LLM / TTS pipeline combinations across the four AC prompt categories
(short/long, with/without tool calls):

```bash
# Dry-run (no backend required — validates config + schema output)
python runner/run_component_benchmark.py --config configs/component-benchmark.yaml --dry-run

# Live run against a running backend
export BENCHMARK_API_URL=http://localhost:8000
export BENCHMARK_API_TOKEN=<your-jwt>
python runner/run_component_benchmark.py --config configs/component-benchmark.yaml
```

Results are written as JSONL to `benchmarks/results/component/` using the harness
schema in `runner/benchmark_schema.py` (consumed by Endri's aggregator).

### View Results

```bash
# Print summary of recent runs
python runner/compare.py

# Export comparison as CSV
python runner/compare.py --output-csv comparison.csv

# Filter by config name (cloud model)
python runner/compare.py --config baseline-cloud --limit 10

# Filter by config name (local model)
python runner/compare.py --config baseline-local --limit 10
```

## Directory Structure

```
benchmarks/
├── configs/              # Experiment specifications (YAML)
│   ├── baseline-cloud.yaml
│   ├── baseline-local.yaml      # Qwen via OpenRouter (#67)
│   └── baseline-oss-gemma.yaml  # Gemma via OpenRouter (#67)
├── runner/               # Runner and comparison tools
│   ├── config.py         # Config schema + validation
│   ├── storage.py        # Result serialization
│   ├── runner.py         # BenchmarkRunner orchestration
│   ├── compare.py        # Comparison and reporting
│   ├── run_benchmark.py  # CLI entry point
│   └── test_runner.py    # Unit tests
├── results/              # Results stored here (JSONL + index)
│   ├── index.csv         # Summary of all runs
│   ├── a1b2c3d4/
│   │   └── results.jsonl # Per-trial metrics
│   └── ...
├── requirements.txt      # Python dependencies
└── README.md             # This file
```

## Experiment Configuration

Define experiments in YAML. See `configs/` for examples.

### Schema

```yaml
name: experiment-baseline              # Unique name for this experiment
description: "Baseline with openai"    # Optional description
provider: openai                       # Provider: local, openai, google, etc.
model: gpt-4o-mini                    # Model name
input_set: tests/inputs/prompts.jsonl # Path to JSONL input file
repetitions: 3                         # Number of trials to run
concurrency: 1                         # Concurrent trials (1 = sequential)
metrics:                               # Metrics to collect
  - latency_e2e                        # End-to-end latency
  - latency_components                 # Per-component breakdown
  - token_usage                        # LLM token counts
  - errors                             # Error tracking
timeout_seconds: 300                   # Trial timeout (optional, default: 300)
tags:                                  # Optional: custom tags
  version: baseline-v1
```

### Valid Metrics

- `latency_e2e` — End-to-end latency from input → response (uses `latency_ms.total` from API when available)
- `latency_components` — Per-component breakdown from `ConversationResponse.latency_ms` (`llm`, `tool_call`, `stt`, `tts`; text path typically has `llm` only)
- `token_usage` — Prompt and completion tokens (see note below)
- `errors` — Error counts and types
- `throughput` — Requests per second

**Note on token_usage:** The backend tracks tokens in Prometheus (`taskorbit_tokens_used_total`, #11). The harness records `token_usage` in results JSONL; live runs currently default to `0` until token counts are exposed on the API response. Use Grafana/Prometheus alongside benchmark JSONL for token analysis today.

## Results Format

### Per-Trial JSONL (`results/run-id/results.jsonl`)

One JSON object per line:

```json
{
  "run_id": "a1b2c3d4",
  "timestamp": "2026-06-18T11:00:00Z",
  "trial_index": 0,
  "metrics": {
    "latency_ms": 150.5,
    "component_latencies": {
      "stt": 10.2,
      "llm": 80.3,
      "tts": 60.0
    },
    "token_usage": {
      "prompt": 50,
      "completion": 25
    },
    "success": true,
    "throughput": 6.67,
    "system_metrics": {
      "cpu_percent": 12.5,
      "memory_rss_mb": 84.2,
      "memory_percent": 31.4,
      "gpu_percent": null,
      "gpu_memory_percent": null
    }
  },
  "environment": {
    "git_sha": "abc123def456...",
    "docker_image": "taskorbit:v1",
    "python_version": "3.11.0",
    "dependencies": {
      "httpx": "0.28.1",
      "PyYAML": "6.0.2",
      "psutil": "7.0.0"
    }
  }
}
```

### Index Summary (`results/index.csv`)

CSV with one row per run:

```csv
run_id,config_name,timestamp,avg_latency_ms,min_latency_ms,max_latency_ms,success_rate,total_trials,throughput_avg,path_to_results
a1b2c3d4,experiment-baseline,2026-06-18T11:00:00Z,150.5,148.0,152.1,1.0,3,6.67,benchmarks/results/a1b2c3d4/results.jsonl
```

## CLI Usage

### Run Benchmark

```bash
python runner/run_benchmark.py --config configs/baseline-cloud.yaml [options]
```

**Options:**
- `--config` (required): Path to experiment config
- `--results-dir`: Output directory (default: `benchmarks/results`)
- `--dry-run`: Simulate without executing trials
- `--upload-metrics`: Push metrics to OpenTelemetry endpoint (future)
- `--verbose`: Enable debug logging

**Examples:**

```bash
# Basic run
python runner/run_benchmark.py --config configs/baseline-cloud.yaml

# Dry run (mock results)
python runner/run_benchmark.py --config configs/baseline-cloud.yaml --dry-run

# Verbose output
python runner/run_benchmark.py --config configs/baseline-cloud.yaml --verbose
```

### Compare Runs

```bash
python runner/compare.py [options]
```

**Options:**
- `--config`: Filter by config name
- `--limit`: Show N most recent runs (default: 5)
- `--output-csv`: Save comparison as CSV
- `--results-dir`: Results directory (default: `benchmarks/results`)

**Examples:**

```bash
# Print text summary of last 5 runs
python runner/compare.py

# Compare last 10 runs of experiment-baseline
python runner/compare.py --config experiment-baseline --limit 10

# Export comparison as CSV
python runner/compare.py --output-csv comparison.csv
```

## Testing

Run unit tests for config parsing, storage, and metrics:

```bash
pytest runner/test_runner.py -v
```

## Reproducibility

### Prerequisites
- Python 3.11+
- Dependencies from `requirements.txt`
- (Optional) Docker for containerized runs

### Key Points
1. **Config files** define reproducible experiment parameters
2. **Results persisted** in structured JSONL + index.csv
3. **Metrics collected** consistently: latency (E2E + components), tokens, errors
4. **Failed runs** tracked: exit code non-zero if any trial fails
5. **Environment captured**: git SHA, Python version, docker image, runtime dependency versions
6. **System metrics captured**: CPU, memory, optional GPU snapshot per trial

## Future Features

- [ ] OpenTelemetry export (--upload-metrics)
- [ ] System metrics collection (CPU, memory, GPU)
- [ ] Matplotlib visualization (plots)
- [ ] Batch experiment execution
- [ ] Statistical significance testing

## Integration with Monitoring

Results are designed to feed into Grafana dashboards. Export JSONL to your analytics platform for:
- Latency trends over time
- Success rate tracking
- Token usage by provider
- Component performance breakdown
