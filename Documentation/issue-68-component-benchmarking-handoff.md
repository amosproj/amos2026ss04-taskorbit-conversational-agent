# Issue #68 — Component Benchmarking: Status

Branch: `Feature-Component-Benchmarking-68`  
Ticket: [#68 Component Benchmarking](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/issues/68)  
PR: [#184](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/pull/184)

---

## Story status (2026-06-27)

| Area | Status |
|------|--------|
| Tool-call timing + `latency_ms` on API | Done |
| Component harness + prompt set (4 AC categories) | Done |
| Tool reliability evaluation (`reliability.py`) | Done |
| Aggregation + `index.csv` + report (`aggregate.py`) | Done |
| Default config recommendation (`recommendation.py`) | Done |
| Voice-path STT/TTS stage measurement (`voice_stages.py`) | Done |
| GPC run script (`benchmarks/scripts/run-gpc-benchmark.sh`) | Done |
| Wiki-style docs (`Documentation/component-benchmarking.md`) | Done |
| **GPC live benchmark run + results filled in** | **Pending** (needs API keys + GPC access) |
| **Merged to `main`** | **Pending** |
| **PO sign-off / peer review** | **Pending** |

---

## Quick run

```bash
# Dry-run (no backend)
cd /path/to/repo
PYTHONPATH=benchmarks/runner python3 benchmarks/runner/run_component_benchmark.py \
  --config benchmarks/configs/component-benchmark.yaml --dry-run

# Live text-only smoke
export BENCHMARK_API_URL=http://localhost:8000
export BENCHMARK_API_TOKEN=<jwt>
PYTHONPATH=benchmarks/runner python3 benchmarks/runner/run_component_benchmark.py \
  --config benchmarks/configs/component-benchmark.yaml --paths text

# Full text + voice (needs DEEPGRAM_API_KEY, ELEVENLABS_API_KEY)
export DEEPGRAM_API_KEY=<key>
export ELEVENLABS_API_KEY=<key>
PYTHONPATH=benchmarks/runner python3 benchmarks/runner/run_component_benchmark.py \
  --config benchmarks/configs/component-benchmark.yaml

# Aggregate + recommendation
PYTHONPATH=benchmarks/runner python3 benchmarks/runner/aggregate.py \
  --results-dir benchmarks/results --report \
  --write-report benchmarks/results/component-benchmark-report.txt
```

GPC standardized run:

```bash
./benchmarks/scripts/run-gpc-benchmark.sh
```

---

## Implementation map

| Module | Purpose |
|--------|---------|
| `backend/.../orchestration/__init__.py` | Tool-call `perf_counter`, `latency_ms` on response |
| `benchmarks/prompts/component_prompts.json` | 6 prompts across 4 AC categories |
| `benchmarks/runner/component_runner.py` | Multi-turn runner; `text` and `voice` paths |
| `benchmarks/runner/voice_stages.py` | Direct STT/TTS provider timing for voice rows |
| `benchmarks/runner/reliability.py` | Authoritative tool reliability verdicts |
| `benchmarks/runner/recommendation.py` | Default config picker (latency → reliability) |
| `benchmarks/runner/aggregate.py` | JSONL → `index.csv` + report + recommendation |
| `benchmarks/configs/component-benchmark.yaml` | 2 configs, 5 reps, text + voice paths |
| `Documentation/component-benchmarking.md` | Team wiki (fill GPC results table after run) |

---

## Remaining to close the story

1. **Run on GPC** with production-like keys (5 reps × 2 configs × 6 prompts × 2 paths)
2. **Paste results** into `Documentation/component-benchmarking.md` GPC table
3. **Merge PR #184** after peer review
4. **PO approval** and release agreement

---

## Voice path note

Voice rows measure STT (Deepgram prerecorded API + reference audio) and TTS (direct provider API) around the same conversation orchestration used on the text path. LiveKit worker latency is tracked separately in Prometheus/Grafana for production voice calls; the harness uses provider APIs for reproducible cross-config comparison without a LiveKit session.

---

## Related

- **#86** — general LLM benchmark harness (`run_benchmark.py`)
- **#68** — component STT/LLM/TTS matrix (`run_component_benchmark.py`)
