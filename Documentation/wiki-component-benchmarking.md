# Component Benchmarking

**Issue:** [#68 Component Benchmarking](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/68)  
**Branch:** `Feature-Component-Benchmarking-68`  
**PR:** [#184](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/pull/184)  

---

## Overview

Component benchmarking compares **STT / LLM / TTS** pipeline configurations on:

- **Latency** — per-stage and end-to-end via real `/v1/conversations/process` API calls
- **Tool-call reliability** — correct tool selected; for `data_extraction`, whether extracted values appear in the reply

**Scope:** text + voice paths.

| Path | What is measured |
|------|------------------|
| `text` | `llm_call`, `tool_call`, `total` |
| `voice` | Same plus STT (Deepgram) and TTS (Deepgram) provider timing |

---

## Implementation status

| Area | Status |
|------|--------|
| Benchmark harness | ✅ Done |
| 4 prompt categories (short/long, ± tools) | ✅ Done |
| 2 pipeline configs in YAML | ✅ Done |
| Per-stage `latency_ms` on API response | ✅ Done |
| Voice-path STT/TTS timing | ✅ Done |
| Tool reliability layer | ✅ Done |
| Aggregation + recommendation | ✅ Done |
| **GPC standardized run** | **✅ Completed** |
| **Wiki results table** | **✅ Filled below** |
| Merge to `main` + PO sign-off | Pending |

---

## Pipeline configurations

| Label | STT | LLM | TTS |
|-------|-----|-----|-----|
| `oss-ollama-gemma4-deepgram` | Deepgram nova-2 | Ollama gemma4:26b (GCE VM) | Deepgram aura-2-andromeda |
| `oss-ollama-qwen3-deepgram` | Deepgram nova-2 | Ollama qwen3.5:9b (GCE VM) | Deepgram aura-2-andromeda |

Ollama runs on a team GCE VM at `http://35.231.129.211:11434/`. Before timed runs the harness primes the model into VRAM with a configurable warmup + 30s settle buffer.

---

## Benchmark results

### GPC standardized run

| | |
|---|---|
| **Date** | 2026-07-01 |
| **Environment** | Local backend (`localhost:8000`) + Ollama GCE VM |
| **Repetitions** | 1 per config/path |
| **Path** | text + voice |
| **Total rows** | 48 |
| **Success rate** | **100%** (48/48) |

#### Headline comparison

| Config | Avg total text (ms) | Avg total voice (ms) | Reliability |
|--------|---------------------|----------------------|-------------|
| `oss-ollama-gemma4-deepgram` | **4,682** | **4,658** | **91.7%** ★ |
| `oss-ollama-qwen3-deepgram` | 4,851 | 4,983 | 91.7% |

**Recommended default:** `oss-ollama-gemma4-deepgram`  
**Reason:** Lowest avg total latency (text: 4,682 ms, voice: 4,658 ms); reliability tied at 91.7%.

#### Per-stage averages (text)

| Config | llm_call (ms) | tool_call (ms) | total (ms) |
|--------|---------------|----------------|------------|
| `oss-ollama-gemma4-deepgram` | 1,607 | 0.1 | 4,682 |
| `oss-ollama-qwen3-deepgram` | 1,761 | 0.2 | 4,851 |

#### Per-stage averages (voice)

| Config | llm_call (ms) | tool_call (ms) | total (ms) |
|--------|---------------|----------------|------------|
| `oss-ollama-gemma4-deepgram` | 1,569 | 1.0 | 4,658 |
| `oss-ollama-qwen3-deepgram` | 1,908 | 0.1 | 4,983 |

#### Latency by category (text)

| Category | gemma4 (ms) | qwen3.5 (ms) |
|----------|-------------|--------------|
| `short_no_tool` | 3,275 | 3,358 |
| `short_with_tool` | 4,480 | 4,676 |
| `long_no_tool` | 4,864 | 5,045 |
| `long_with_tool` | 5,175 | 5,366 |

#### Latency by category (voice)

| Category | gemma4 (ms) | qwen3.5 (ms) |
|----------|-------------|--------------|
| `short_no_tool` | 3,185 | 3,377 |
| `short_with_tool` | 4,473 | 4,170 |
| `long_no_tool` | 4,741 | 5,402 |
| `long_with_tool` | 5,235 | 5,537 |

#### Reliability by category

| Category | gemma4 | qwen3.5 |
|----------|--------|---------|
| `short_no_tool` | 100% | 100% |
| `short_with_tool` | 100% | 100% |
| `long_no_tool` | 100% | 100% |
| `long_with_tool` | 80% | 80% |

Both models show the same reliability pattern: 100% on all categories except `long_with_tool` (appointment booking with `data_extraction`), where one of five prompts failed to incorporate extracted values into the reply.

---

## Results file

```
benchmarks/results/gpc-run-20260702T004141/
├── component/
│   └── 2026-07-01T22-41-41_component_benchmark.jsonl    # raw 48 rows
├── component-benchmark-report.txt    # full text report
├── index.csv                         # per-config/path summary
├── benchmark-summary.csv             # Excel-friendly export
└── run.log                           # harness output
```

---

## Repo map

| Path | Purpose |
|------|---------|
| `benchmarks/runner/run_component_benchmark.py` | CLI entry point |
| `benchmarks/runner/component_runner.py` | Multi-turn API driver (text + voice paths) |
| `benchmarks/runner/voice_stages.py` | Direct STT/TTS provider timing for voice rows |
| `benchmarks/runner/ollama_warmup.py` | VRAM primer + settle buffer |
| `benchmarks/runner/turn_expectations.py` | Per-turn tool/status expectations |
| `benchmarks/runner/reliability.py` | Authoritative reliability verdicts |
| `benchmarks/runner/aggregate.py` | JSONL → index.csv + report |
| `benchmarks/runner/recommendation.py` | Default config picker |
| `benchmarks/configs/component-benchmark.yaml` | Reference config matrix |
| `benchmarks/configs/component-benchmark-oss-only.yaml` | OSS-only config (used for GPC run) |
| `benchmarks/scripts/run-gpc-benchmark.sh` | GPC one-shot script |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-01 | GPC standardized run completed — 48/48 success (gemma4:26b vs qwen3.5:9b, text+voice) |
| 2026-07-01 | Ollama VRAM warmup + 30s buffer before timed benchmark runs |
| 2026-07-01 | Voice path restored in standard config |
| 2026-06-30 | Initial implementation; text smoke run (failed — OpenAI 429/Ollama timeouts) |
