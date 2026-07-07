# Component Benchmarking Demo — Issue #68

Short runbook for live demos. **Terminal only** — no frontend required.

---

## What this ticket does (30-second pitch)

We benchmark **two STT / LLM / TTS pipeline configs** across the same prompts:

| Config | STT | LLM | TTS |
|--------|-----|-----|-----|
| `cloud-openai-deepgram-elevenlabs` | Deepgram nova-3 | OpenAI gpt-4o-mini | ElevenLabs |
| `oss-ollama-deepgram-deepgram` | Deepgram nova-2 | Ollama gemma4:26b | Deepgram |

**Prompt coverage (4 AC categories):**

- Short / long
- With / without tool calls

**What we measure:**

- Per-stage latency: STT, LLM, tool call, TTS
- Tool reliability: correct tool selected, result in reply
- Default config recommendation: fastest latency, reliability as tie-break

**Output:** JSONL results → aggregated report → recommended default config.

---

## Acceptance criteria vs status

| AC | Delivered in code | Demo today |
|----|-------------------|------------|
| Multiple runs, 2 configs, standardized env | `component-benchmark.yaml`, `run-gpc-benchmark.sh` | Dry-run + optional real report |
| Voice E2E latency | `voice_stages.py` | Mention; voice needs API keys |
| Per-stage latency | Backend `latency_ms` + harness | Visible in report |
| Short/long, with/without tools | `component_prompts.json` | Visible in report categories |
| Tool reliability | `reliability.py` | Visible in report |
| Structured results + wiki recommendation | `aggregate.py`, `recommendation.py` | Report file on disk |

**Pending (can be done by anyone with GPC access):**

- Standardized **GPC run** (5 repetitions)
- Paste results into `Documentation/component-benchmarking.md` wiki table

> The measurement harness is complete. GPC + wiki fill-in is a follow-up, not a blocker for the PR.

---

## Prerequisites (one-time)

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
pip install -r benchmarks/requirements.txt
```

Keys are loaded automatically from `backend/.env` by the demo script.

---

## Demo Step 1 — Dry run (recommended live demo, ~5 seconds)

**No backend. No API keys. Shows full pipeline.**

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
./benchmarks/scripts/run-local-demo.sh dry-run
```

**What to point at in the output:**

- `total_rows: 12` — harness ran all prompts × both configs
- `success_rows: 12` — all rows written to JSONL
- **Stage Latency Averages** — `llm_call`, `tool_call`, `total`
- **By Category** — four prompt types
- **Reliability** — pass rate per category
- **Recommended:** `cloud-openai-deepgram-elevenlabs` (or tied config)

**Say:**

> "This proves config loading, prompt execution, JSONL persistence, aggregation, and default config recommendation — the full AC6 pipeline."

**Result files:**

```text
benchmarks/results/demo-<timestamp>/component/*.jsonl
benchmarks/results/demo-<timestamp>/component-benchmark-report.txt
```

---

## Demo Step 2 — Show real API results (optional, read-only)

If you already ran a live benchmark earlier, show the report without re-running (~16 min live run):

```bash
cat benchmarks/results/local-20260630T204656/component-benchmark-report.txt
```

**Say:**

> "This is from a real backend run. Ollama averaged ~22s with ~92% tool reliability. OpenAI failed on quota — that's an API billing issue, not the harness."

To run a **new** live text benchmark (backend must be running):

```bash
# Terminal 1 — start backend (if not already up)
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/backend
poetry run uvicorn taskorbit.api.main:app --reload

# Terminal 2 — live benchmark (~10–20 min)
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
curl http://localhost:8000/health
./benchmarks/scripts/run-local-demo.sh text
```

---

## Quick reference — all commands

| Goal | Command |
|------|---------|
| Dry-run demo | `./benchmarks/scripts/run-local-demo.sh dry-run` |
| Live text benchmark | `./benchmarks/scripts/run-local-demo.sh text` |
| Live voice benchmark | `./benchmarks/scripts/run-local-demo.sh voice` |
| View latest report | `cat benchmarks/results/demo-*/component-benchmark-report.txt` |
| GPC standardized run | `./benchmarks/scripts/run-gpc-benchmark.sh` |

---

## FAQ for the audience

**Do we need the frontend?**  
No. The harness calls `POST /v1/conversations/process` directly.

**Do we need `BENCHMARK_API_TOKEN` locally?**  
No. Dev auth uses the seeded backend user.

**Is ElevenLabs blocking prod?**  
No. ElevenLabs is only used for cloud-config **voice TTS**. Text benchmarks and the oss Deepgram config work without it.

**What is GPC?**  
Our standardized Google Cloud environment. Same script, production-like keys, 5 repetitions — results go into the wiki table.

**Who does the GPC follow-up?**  
Anyone with GPC access and working API quota. Script is ready: `benchmarks/scripts/run-gpc-benchmark.sh`.

---

## Key code files (if asked)

| Area | File |
|------|------|
| Runner | `benchmarks/runner/component_runner.py` |
| Voice STT/TTS | `benchmarks/runner/voice_stages.py` |
| Tool reliability | `benchmarks/runner/reliability.py` |
| Aggregation + report | `benchmarks/runner/aggregate.py` |
| Recommendation | `benchmarks/runner/recommendation.py` |
| Configs | `benchmarks/configs/component-benchmark.yaml` |
| Prompts | `benchmarks/prompts/component_prompts.json` |
| Backend latency | `backend/src/taskorbit/orchestration/__init__.py` |
| Full runbook | `Documentation/component-benchmarking.md` |

---

## Closing line for the demo

> "Issue #68 harness is implemented and tested. Today we showed the end-to-end flow. The standardized GPC run and wiki results table are the only remaining operational step — ready for whoever has GPC access."
