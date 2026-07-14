# Component Benchmarking

**Issue:** [#68 Component Benchmarking](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/68)  
**Merged:** PR [#184](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/pull/184) → `main`  

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
| **GPC standardized run** | **✅ Completed (2026-07-14)** |
| **Wiki results table** | **✅ Filled below** |
| Merge to `main` + PO sign-off | ✅ Merged (#184) |

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
| **Date** | 2026-07-14 |
| **Environment** | Cloud Run Backend API + Ollama GCE VM |
| **Repetitions** | 1 per config/path |
| **Path** | text + voice |
| **Row accounting** | 2 configs × 2 paths × 12 turn-level rows = 48 |
| **Total rows** | 48 |
| **Success rate** | **100%** (48/48) |

#### Headline comparison

| Config | Avg total text (ms) | Avg total voice (ms) | Reliability |
|--------|---------------------|----------------------|-------------|
| `oss-ollama-gemma4-deepgram` | **4,508** | **5,477** | **91.7%** ★ |
| `oss-ollama-qwen3-deepgram` | 4,596 | 7,694 | 91.7% |

**Recommended default:** `oss-ollama-gemma4-deepgram`  
**Reason:** Lowest avg total latency (text: 4,508 ms, voice: 5,477 ms); reliability tied at 91.7%.

#### Per-stage averages (text)

| Config | llm_call (ms) | tool_call (ms) | total (ms) |
|--------|---------------|----------------|------------|
| `oss-ollama-gemma4-deepgram` | 1,555 | 0.0 | 4,508 |
| `oss-ollama-qwen3-deepgram` | 1,691 | 0.0 | 4,596 |

#### Per-stage averages (voice)

| Config | STT (ms) | llm_call (ms) | tool_call (ms) | TTS (ms) | total (ms) |
|--------|----------|---------------|----------------|----------|------------|
| `oss-ollama-gemma4-deepgram` | 1,445 | 1,512 | 0.0 | 2,646 | 5,477 |
| `oss-ollama-qwen3-deepgram` | 1,898 | 1,899 | 0.0 | 4,054 | 7,694 |

#### Latency by category (text)

| Category | gemma4 (ms) | qwen3.5 (ms) |
|----------|-------------|--------------|
| `short_no_tool` | 3,086 | 3,286 |
| `short_with_tool` | 4,597 | 4,628 |
| `long_no_tool` | 4,666 | 4,650 |
| `long_with_tool` | 4,965 | 5,082 |

#### Latency by category (voice)

| Category | gemma4 (ms) | qwen3.5 (ms) |
|----------|-------------|--------------|
| `short_no_tool` | 7,284 | 7,208 |
| `short_with_tool` | 4,380 | 6,217 |
| `long_no_tool` | 5,942 | 8,864 |
| `long_with_tool` | 4,915 | 7,778 |

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
benchmarks/results/gpc-20260714T192935/
├── component/
│   └── 2026-07-14T19-29-36_component_benchmark.jsonl    # raw 48 rows
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
| 2026-07-14 | GPC standardized run completed on Production API — 48/48 success (gemma4:26b vs qwen3.5:9b, text+voice) |
| 2026-07-01 | Ollama VRAM warmup + 30s buffer before timed benchmark runs |
| 2026-07-01 | Voice path restored in standard config |
| 2026-06-30 | Initial implementation; text smoke run (failed — OpenAI 429/Ollama timeouts) |
