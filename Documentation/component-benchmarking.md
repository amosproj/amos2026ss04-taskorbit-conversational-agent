# Component Benchmarking — #68

## Overview

Component benchmarking evaluates end-to-end latency and tool-call reliability across different **STT / LLM / TTS** pipeline configurations. Unlike the general LLM latency experiments in `run_benchmark.py`, the component benchmark drives real `ConversationResponse` calls through the API and measures per-stage latency (`stt_processing`, `llm_call`, `tool_call`, `tts_synthesis`, `total`).

## Prompt categories

The benchmark covers the four AC-required categories defined in `benchmarks/prompts/component_prompts.json`:

| Category | Turns | Tool expected | Prompt |
|---|---|---|---|
| `short_no_tool` | 1 | none | Business hours, services inquiry |
| `short_with_tool` | 1 | `agent_transfer`, `end_call` | Transfer to tech support, end call |
| `long_no_tool` | 3 | none | Multi-turn tech troubleshooting |
| `long_with_tool` | 5 | `data_extraction` | Appointment booking (name, email, phone, date) |

Each prompt maps to a real agent template in `prompts.py` with tools attached (or empty for no-tool categories).

## Pipeline configurations

At least **two** provider combinations are compared. The default config (`benchmarks/configs/component-benchmark.yaml`) ships with:

| Label | STT | LLM | TTS |
|---|---|---|---|
| `cloud-openai-deepgram-elevenlabs` | Deepgram nova-3 | OpenAI gpt-4o-mini | ElevenLabs multilingual_v2 |
| `oss-openrouter-deepgram-deepgram` | Deepgram nova-2 | OpenRouter Llama 3.3 70B | Deepgram aura-2-andromeda |

## How to run

### Prerequisites

- A running backend at `BENCHMARK_API_URL` (default `http://localhost:8000`)
- `BENCHMARK_API_TOKEN` set for authenticated requests
- Provider API keys configured in the backend `.env`

### Live run

```bash
export BENCHMARK_API_URL=http://localhost:8000
export BENCHMARK_API_TOKEN=<jwt>

cd benchmarks
pip install -r requirements.txt

python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml
```

### Dry run

Validates the config and writes mock rows without a backend:

```bash
python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml \
  --dry-run
```

### Voice path

The YAML `paths` field controls which pipeline modes run:

- `text` — LLM + tool latency via `/v1/conversations/process`
- `voice` — same conversation flow plus direct STT/TTS provider timing

Voice rows require `DEEPGRAM_API_KEY` (STT + Deepgram TTS) and `ELEVENLABS_API_KEY`
(ElevenLabs TTS). STT uses a fixed reference audio URL for comparable latency across runs.

```bash
# Text only (fast smoke test)
python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml \
  --paths text

# Full text + voice matrix (default in component-benchmark.yaml)
python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml
```

### Repetitions

The YAML `repetitions` field controls how many times each prompt × config combination is run. **5 repetitions** is the recommended minimum for statistically meaningful latency averages.

## Output

### JSONL rows

Results are written to `benchmarks/results/component/<timestamp>_component_benchmark.jsonl`.

Each row contains:
- `config` — STT/LLM/TTS provider and model names
- `config_label` — human-readable config name
- `prompt` — category, id, text, expects_tool, expected_tool_type
- `path` — `"text"` (voice-path rows use `"voice"` and must not be mixed in averages)
- `latency_ms` — per-stage timing + `cumulative_total` for multi-turn
- `tool_reliability` — `tool_was_invoked`, `invoked_tool_type`, `correct_tool_selected`, `result_incorporated_in_reply`
- `turn_index` / `turn_count` — multi-turn metadata
- `status` / `error`

### Aggregation

After a live run, aggregate the results:

```bash
python runner/aggregate.py --results-dir ../results --report
```

This produces:
- `benchmarks/results/index.csv` — one row per (run_id, config_label, path) with pipeline models and latency stats
- A text report with per-config per-stage latency averages and authoritative reliability summary per category
- A **default configuration recommendation** (lowest avg latency; reliability tie-break within 10%)

Write the full report to a file (for wiki paste):

```bash
python runner/aggregate.py \
  --results-dir benchmarks/results/gpc-YYYYMMDD \
  --write-report benchmarks/results/gpc-YYYYMMDD/component-benchmark-report.txt
```

### Example report output

```
Component Benchmark Report

Path: text

Config: cloud-openai-deepgram-elevenlabs  (18 rows)
  Stage Latency Averages (ms):
    llm_call               120.0
    tool_call              5.0
    total                  150.0
  By Category:
    long_no_tool                    3 rows  3/3 success  150.0 ms avg
    long_with_tool                  3 rows  3/3 success  150.0 ms avg
    short_no_tool                   6 rows  6/6 success  150.0 ms avg
    short_with_tool                 6 rows  6/6 success  150.0 ms avg
  Reliability (authoritative):
    short_no_tool                   6 / 6   pass  reliability_rate: 100.0%
    long_no_tool                    3 / 3   pass  reliability_rate: 100.0%
```

## Tool reliability evaluation

The authoritative reliability layer (`benchmarks/runner/reliability.py`) evaluates each row:

| Check | Rule |
|---|---|
| `tool_was_invoked` | `tool_invoked is not None` |
| `correct_tool_selected` | `invoked_tool_type == expected_tool_type` (or no tool when `expects_tool=false`) |
| `result_incorporated_in_reply` | For `data_extraction` — extracted slot values appear in reply content |

Immediate hand-off tools (`agent_transfer`, `end_call`) have `result_incorporated` marked as N/A since there is no reply body.

## Default configuration recommendation

`aggregate.py` computes the recommended default config automatically from JSONL results.

### Methodology

1. **Primary criterion:** lowest end-to-end latency averaged across all prompt categories
2. **Secondary criterion:** highest tool-call reliability rate when latencies are within 10%

Perform **5 repetitions** per config in the standardized GPC environment. After the run:

```bash
./benchmarks/scripts/run-gpc-benchmark.sh
```

Paste the generated `component-benchmark-report.txt` recommendation section below after your GPC run.

### GPC results (fill in after standardized run)

| Config | Avg total latency text (ms) | Avg total latency voice (ms) | Tool reliability rate | Recommendation |
|---|---|---|---|---|
| `cloud-openai-deepgram-elevenlabs` | — | — | — | — |
| `oss-openrouter-deepgram-deepgram` | — | — | — | — |

**Recommended default:** _(auto-filled from `aggregate.py --report` after GPC run)_

## Related

- **Issue #68** — Component Benchmarking (this work)
- **Issue #86** — Benchmarking Environment (general LLM harness)
- `benchmarks/runner/` — runner, schema, config, reliability, aggregation modules
- `benchmarks/configs/component-benchmark.yaml` — standard config
- `benchmarks/prompts/component_prompts.json` — prompt definitions
