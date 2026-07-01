# Component Benchmarking

**Issue:** [#68 Component Benchmarking](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/68)  
**Branch:** `Feature-Component-Benchmarking-68`  
**PR:** [#184](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/pull/184)  
**Status:** Harness complete — GPC standardized run + results table pending

---

## Overview

Component benchmarking compares **STT / LLM / TTS** pipeline configurations on:

- **Latency** — per-stage and end-to-end via real `/v1/conversations/process` API calls
- **Tool-call reliability** — correct tool selected; for `data_extraction`, whether extracted values appear in the reply

Unlike the general LLM harness ([#86](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/86), `run_benchmark.py`), this matrix drives full agent conversations with tools attached.

**Current scope:** **text + voice paths** (both in `component-benchmark.yaml`).

| Path | What is measured |
|------|------------------|
| `text` | `llm_call`, `tool_call`, `total` via the conversation API |
| `voice` | Same orchestration plus direct **STT** (Deepgram) and **TTS** (ElevenLabs or Deepgram) provider timing (`voice_stages.py`) |

> **LiveKit mic → agent audio** is not what the harness measures. Production voice calls are tracked separately in Prometheus/Grafana. The voice path uses provider APIs + reference audio for reproducible cross-config comparison without a LiveKit session.

---

## User story

> As a developer, I want to run latency-focused benchmark tests across different STT, LLM and TTS pipeline configurations, so that I can identify which configuration provides the fastest end-to-end response time while still supporting reliable tool calls.

---

## Implementation status

| Area | Status |
|------|--------|
| Benchmark harness (`run_component_benchmark.py`) | Done |
| 4 prompt categories (short/long, ± tools) | Done |
| 2 pipeline configs in YAML | Done |
| Per-stage `latency_ms` on API | Done |
| Voice-path STT/TTS timing (`voice_stages.py`) | Done |
| Ollama VRAM warmup + buffer (`ollama_warmup.py`) | Done |
| Tool reliability layer (`reliability.py`) | Done |
| Aggregation + `index.csv` (`aggregate.py`) | Done |
| Default config recommendation (`recommendation.py`) | Done |
| GPC run script (`run-gpc-benchmark.sh`) | Done |
| **GPC standardized run (5 reps)** | **Pending** |
| **GPC results table below** | **Pending** |
| Merge to `main` + PO sign-off | Pending |

---

## Prompt categories

Defined in `benchmarks/prompts/component_prompts.json`:

| Category | Turns | Tool expected | Example |
|----------|-------|---------------|---------|
| `short_no_tool` | 1 | none | Business hours, services inquiry |
| `short_with_tool` | 1 | `agent_transfer`, `end_call` | Transfer to tech support; end call |
| `long_no_tool` | 3 | none | Multi-turn tech troubleshooting |
| `long_with_tool` | 5 | `data_extraction` (final turn only) | Appointment booking (name, email, phone, date) |

Each prompt uses a real agent template in `benchmarks/runner/prompts.py` with the appropriate tools configured.

---

## Pipeline configurations

At least **two** provider combinations are compared (`benchmarks/configs/component-benchmark.yaml`):

| Label | STT | LLM | TTS |
|-------|-----|-----|-----|
| `cloud-openai-deepgram-elevenlabs` | Deepgram nova-3 | OpenAI gpt-4o-mini | ElevenLabs multilingual_v2 |
| `oss-ollama-deepgram-deepgram` | Deepgram nova-2 | Ollama gemma4:26b (GCE VM) | Deepgram aura-2-andromeda |

**Note:** OSS config uses self-hosted Ollama (`OLLAMA_BASE_URL` on the backend, e.g. `http://35.231.129.211:11434/`). OpenRouter is not required for the standard matrix.

**Ollama VRAM warmup:** Before timed runs on the OSS config, the harness sends a **primer LLM request** to load the model into GPU memory, then waits a configurable **buffer** (default **30s**, set in YAML). This keeps cold-start load time out of benchmark latency. Override at runtime: `export OLLAMA_WARMUP_BUFFER_SECONDS=45`. Disable: `ollama_warmup.enabled: false` in the YAML.

---

## How to run

### Prerequisites

- Backend running at `BENCHMARK_API_URL` (default `http://localhost:8000`)
- `BENCHMARK_API_TOKEN` only if auth is enabled (optional in local dev)
- Backend `.env`: `OPENAI_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` for the two configs
- Voice path additionally needs `DEEPGRAM_API_KEY` and `ELEVENLABS_API_KEY` (loaded by `run-local-demo.sh` from `backend/.env`)

### Dry run (no backend, ~5 seconds)

```bash
cd benchmarks
pip install -r requirements.txt
export PYTHONPATH=runner

python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml \
  --dry-run
```

### Live run (text + voice, default config)

```bash
export BENCHMARK_API_URL=http://localhost:8000
export PYTHONPATH=runner

python runner/run_component_benchmark.py \
  --config configs/component-benchmark.yaml
```

### Local smoke (1 repetition)

From repo root (loads keys from `backend/.env`):

```bash
./benchmarks/scripts/run-local-demo.sh text    # text path only
./benchmarks/scripts/run-local-demo.sh voice   # voice path only (STT + TTS timing)
./benchmarks/scripts/run-local-demo.sh dry-run # no backend, ~5 seconds
```

Or manually:

```bash
export BENCHMARK_API_URL=http://localhost:8000
export PYTHONPATH=runner

python runner/run_component_benchmark.py \
  --config configs/component-benchmark-smoke.yaml \
  --paths voice
```

### GPC standardized run

```bash
export BENCHMARK_API_URL=http://localhost:8000
export BENCHMARK_API_TOKEN=<jwt-if-needed>

./benchmarks/scripts/run-gpc-benchmark.sh
```

**Recommended:** 5 repetitions per config (set in `component-benchmark.yaml`).

### Aggregate results

```bash
export PYTHONPATH=runner

python runner/aggregate.py \
  --results-dir benchmarks/results/gpc-YYYYMMDD \
  --report \
  --write-report benchmarks/results/gpc-YYYYMMDD/component-benchmark-report.txt
```

---

## Output format

### JSONL (`benchmarks/results/component/<timestamp>_component_benchmark.jsonl`)

Each row includes:

- `config` / `config_label` — STT, LLM, TTS providers and models
- `prompt` — category, id, text, `expects_tool`, `expected_tool_type`, `expected_status`
- `path` — `"text"` or `"voice"`
- `latency_ms` — text: `llm_call`, `tool_call`, `total`, `cumulative_total`; voice adds `stt_processing`, `tts_synthesis`, `voice_turn`
- `tool_reliability` — invocation, correct tool, result incorporated
- `turn_index` / `turn_count`
- `status` / `error`

### Index (`benchmarks/results/index.csv`)

One row per `(run_id, config_label, path)` with latency stats and success rate. Intended for tooling (`compare.py`).

### Excel-friendly export (PO demo)

Generated alongside `index.csv` by `aggregate.py` as a **single file**:

| File | Content |
|------|---------|
| `benchmark-summary.csv` | **Overall** rows (1 per config + path) plus **By category** rows (short/long, ± tools) |

Filter the `Section` column in Excel: `Overall` for the headline comparison, `By category` for AC prompt breakdown. Columns use plain English headers, `83.3%` rates, `2,655.0` ms formatting, and **Recommended** Yes/No on overall rows only.

---

## Tool reliability

Authoritative evaluation in `benchmarks/runner/reliability.py`:

| Check | Rule |
|-------|------|
| No-tool prompts | No tool must fire |
| With-tool prompts | Correct `invoked_tool_type` must match `expected_tool_type` |
| `data_extraction` | Extracted slot values must appear in reply text (fails reliability if not) |
| `agent_transfer` / `end_call` | Result incorporation N/A (immediate hand-off) |

Multi-turn prompts only expect a tool on the **final turn** (`tool_on_final_turn_only`).

---

## Default configuration recommendation

Computed automatically by `aggregate.py` / `recommendation.py`:

1. **Primary:** lowest average `latency_ms.total` across all categories  
2. **Secondary:** highest tool reliability when latencies are within **10%**

---

## Benchmark results

### GPC standardized run (final — pending)

> **Fill this section after the standardized GPC run.**  
> Copy numbers from `component-benchmark-report.txt` → **Default Configuration Recommendation** section.

**Environment:** GPC _(date: ______)_  
**Repetitions:** 5  
**Path:** text + voice

| Config | Avg total text (ms) | Avg total voice (ms) | Tool reliability rate | Notes |
|--------|---------------------|----------------------|----------------------|-------|
| `cloud-openai-deepgram-elevenlabs` | — | — | — | |
| `oss-ollama-deepgram-deepgram` | — | — | — | |

**Recommended default:** _TBD after GPC run_

**Reason:** _TBD (from `aggregate.py --report`)_

#### Per-stage averages (text path, GPC)

| Config | llm_call (ms) | tool_call (ms) | total (ms) |
|--------|---------------|----------------|------------|
| `cloud-openai-deepgram-elevenlabs` | — | — | — |
| `oss-ollama-deepgram-deepgram` | — | — | — |

#### Per-stage averages (voice path, GPC)

| Config | stt_processing (ms) | llm_call (ms) | tts_synthesis (ms) | total (ms) |
|--------|---------------------|---------------|----------------------|------------|
| `cloud-openai-deepgram-elevenlabs` | — | — | — | — |
| `oss-ollama-deepgram-deepgram` | — | — | — | — |

#### Reliability by category (GPC)

| Category | cloud-openai | oss-ollama |
|----------|--------------|------------|
| `short_no_tool` | — | — |
| `short_with_tool` | — | — |
| `long_no_tool` | — | — |
| `long_with_tool` | — | — |

---

### Local voice smoke run (draft — NOT GPC)

**Date:** 2026-07-01  
**Environment:** Local Docker (`localhost:8000`)  
**Repetitions:** 1 (`component-benchmark-smoke.yaml`, `--paths voice`)  
**Path:** voice  
**Results file:** `benchmarks/results/demo-20260701T120044/`

> **Not used for final recommendation.** Single repetition, local keys. Use for demo evidence only; GPC run (5 reps) is authoritative.

| Config | Avg total voice (ms) | Tool reliability | Voice turns |
|--------|----------------------|------------------|-------------|
| `cloud-openai-deepgram-elevenlabs` | 2,655.3 | 83.3% | 12 |
| `oss-ollama-deepgram-deepgram` | 8,933.2 | 91.7% | 12 |

_Run total: 24 rows, 13 succeeded / 11 failed (strict per-turn assertions on cloud config)._

**Per-stage (voice path):**

| Config | stt_processing | llm_call | tts_synthesis | total |
|--------|----------------|----------|---------------|-------|
| `cloud-openai-deepgram-elevenlabs` | 1,531 ms | — | 1,124 ms | 2,655 ms |
| `oss-ollama-deepgram-deepgram` | 1,441 ms | 4,849 ms | 3,047 ms | 8,933 ms |

**Draft recommendation (smoke only):** `cloud-openai-deepgram-elevenlabs` — lowest avg voice latency.

**Final recommendation:** _Pending standardized GPC run (5 reps, text + voice) with stable API access._

---

### Local text smoke run (draft — NOT GPC, failed)

**Date:** 2026-06-30  
**Environment:** Local Docker (`localhost:8000`)  
**Repetitions:** 1  
**Path:** text  

> **Not used.** OpenAI was rate-limited (HTTP 429); Ollama hit LLM timeouts. Low success rate (6/24 rows). Superseded by 2026-07-01 voice smoke for demo purposes.

---

## Repo map

| Path | Purpose |
|------|---------|
| `benchmarks/runner/run_component_benchmark.py` | CLI entry point |
| `benchmarks/runner/component_runner.py` | Multi-turn API driver (text + voice paths) |
| `benchmarks/runner/voice_stages.py` | Direct STT/TTS provider timing for voice rows |
| `benchmarks/runner/ollama_warmup.py` | Ollama VRAM primer + settle buffer before timed runs |
| `benchmarks/runner/turn_expectations.py` | Per-turn tool/status expectations |
| `benchmarks/runner/reliability.py` | Authoritative reliability verdicts |
| `benchmarks/runner/aggregate.py` | JSONL → `index.csv` + report |
| `benchmarks/runner/recommendation.py` | Default config picker |
| `benchmarks/configs/component-benchmark.yaml` | Standard 5-rep matrix |
| `benchmarks/configs/component-benchmark-smoke.yaml` | 1-rep local smoke |
| `benchmarks/scripts/run-gpc-benchmark.sh` | GPC one-shot script |
| `benchmarks/scripts/run-local-demo.sh` | Local dry-run / text / voice smoke |
| `Documentation/component-benchmarking.md` | In-repo technical doc |
| `Documentation/component-benchmarking-live-run.md` | Live API runbook |

---

## Related

- [#68 Component Benchmarking](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/68) — this feature
- [#86 Benchmarking Environment](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/86) — general LLM harness (`run_benchmark.py`)
- [Self-hosted Ollama inference](Self-Hosted-Inference) — OSS LLM VM setup (see also `Documentation/self-hosted-inference.md` in repo)

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-30 | Wiki page created; OSS config switched to Ollama; per-turn reliability fixes |
| 2026-06-30 | Local text smoke run (failed — 429/timeouts); GPC access requested from infra team |
| 2026-07-01 | Voice path restored in standard config; local voice smoke run completed (`demo-20260701T120044`) |
| 2026-07-01 | Ollama VRAM warmup + 30s buffer before OSS timed benchmark runs |
| _GPC run date_ | GPC results table filled after standardized benchmark (5 reps, text + voice) |
