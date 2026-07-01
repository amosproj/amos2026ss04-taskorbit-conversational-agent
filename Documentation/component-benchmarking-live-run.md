# Component Benchmarking — Live Run (Real API Keys)

Run the #68 harness against the **real backend** and **real provider APIs**.  
Terminal only — **no frontend**.

---

## What you need before starting

| Requirement | Required for | How to check |
|-------------|--------------|--------------|
| Backend running | All live runs | `curl http://localhost:8000/health` |
| `backend/.env` with keys | LLM + voice | See key table below |
| `pip install -r benchmarks/requirements.txt` | Harness | One-time setup |
| ~10–20 min | Text smoke run | Grab coffee |
| ~30+ min | Full 5-rep run | Plan accordingly |

**You do NOT need:**

- Frontend
- `BENCHMARK_API_TOKEN` (local dev uses seeded user)
- Google Cloud login (unless running on GPC)

---

## API keys — what uses what

Keys live in **`backend/.env`**. The demo script loads them automatically.

| Key | Used by | Needed for |
|-----|---------|------------|
| `OPENAI_API_KEY` | Backend | Cloud config LLM (`gpt-4o-mini`) |
| `OLLAMA_BASE_URL` + `OLLAMA_MODEL` | Backend | OSS config LLM (`gemma4:26b`) |
| `DEEPGRAM_API_KEY` | Harness (voice path) | STT timing + Deepgram TTS |
| `ELEVENLABS_API_KEY` | Harness (voice path) | Cloud config TTS only |

### Text-only run (`--paths text`)

- Backend reads `OPENAI_API_KEY` and `OLLAMA_*` from `.env`
- **No** Deepgram/ElevenLabs needed in the harness

### Voice run (`--paths voice`)

- Backend still needed for LLM + tools
- Harness also needs `DEEPGRAM_API_KEY` (both configs)
- Harness also needs `ELEVENLABS_API_KEY` (cloud config TTS only)
- OSS config (`oss-ollama-deepgram-deepgram`) works with **Deepgram only**

### Ollama VRAM warmup (OSS config)

Before timed benchmark rows, the harness **loads the Ollama model into GPU memory** with a primer request, then waits a **30s buffer** (configurable). You will see log lines like:

```text
Ollama warmup: loading gemma4:26b into VRAM via http://localhost:8000 ...
Ollama warmup: model responded in 28543 ms
Ollama warmup: waiting 30s buffer for VRAM to settle before timed runs
```

This keeps cold-start VRAM load out of latency numbers — mention it in the PO demo when showing OSS timings.

| Override | Effect |
|----------|--------|
| `ollama_warmup.buffer_seconds` in YAML | Default wait after primer (30) |
| `export OLLAMA_WARMUP_BUFFER_SECONDS=45` | Runtime override |
| `ollama_warmup.enabled: false` | Skip warmup (not recommended for OSS) |

> If OpenAI quota is exceeded (HTTP 429), cloud-config rows fail — Ollama config can still produce real results.

---

## One-time setup

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
pip install -r benchmarks/requirements.txt
```

Ensure the dev user exists (if you get 401 from the backend):

```bash
cd backend
poetry run python scripts/seed_defaults.py
```

---

## Step 1 — Start the backend

**Terminal 1** (leave this running):

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent/backend
poetry run uvicorn taskorbit.api.main:app --reload
```

Verify:

```bash
curl http://localhost:8000/health
# Expected: {"status":"ok","service":"taskorbit-backend",...}
```

---

## Step 2 — Run live text benchmark (recommended first)

**Terminal 2** — smoke config (1 repetition, ~10–20 min):

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
./benchmarks/scripts/run-local-demo.sh text
```

This will:

1. Load keys from `backend/.env` (prints `set` / `missing` only — not the values)
2. Call `POST /v1/conversations/process` for each prompt × config
3. Write JSONL to `benchmarks/results/demo-<timestamp>/component/`
4. Generate `component-benchmark-report.txt`

### Manual equivalent (same thing)

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent

set -a && source backend/.env && set +a
export BENCHMARK_API_URL=http://localhost:8000
export PYTHONPATH=benchmarks/runner

mkdir -p benchmarks/results/my-live-run/component

python3 benchmarks/runner/run_component_benchmark.py \
  --config benchmarks/configs/component-benchmark-smoke.yaml \
  --paths text \
  --results-dir benchmarks/results/my-live-run/component

python3 benchmarks/runner/aggregate.py \
  --results-dir benchmarks/results/my-live-run \
  --report \
  --write-report benchmarks/results/my-live-run/component-benchmark-report.txt
```

---

## Step 3 — View results

```bash
cat benchmarks/results/demo-*/component-benchmark-report.txt | tail -50
```

Or open the latest report:

```bash
ls -t benchmarks/results/demo-*/component-benchmark-report.txt | head -1 | xargs cat
```

**Good run looks like:**

- `success_rows` close to `total_rows`
- Stage averages: `llm_call`, `tool_call`, `total` with real ms values (not 120/150 mock numbers)
- Reliability pass rates per category
- **Recommended:** one config at the bottom

**Common failures:**

| Error | Cause | Fix |
|-------|-------|-----|
| `Could not connect` | Backend not running | Step 1 |
| `OpenAI rate-limited / 429` | Quota/billing | Fix OpenAI key or run OSS config only |
| `Ollama 500` / timeout | Ollama server down/slow | Check `OLLAMA_BASE_URL` reachable |
| Empty report | Wrong results folder | Use `run-local-demo.sh` (fixed path) |

---

## Step 4 — Voice path (optional, real STT + TTS timing)

Only after text run works. Needs **Deepgram**; **ElevenLabs** only for cloud config.

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
./benchmarks/scripts/run-local-demo.sh voice
```

Voice rows add `stt_processing` and `tts_synthesis` to `latency_ms` in the JSONL.

---

## Full standardized run (5 repetitions, text + voice)

For wiki / GPC-style results:

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent
./benchmarks/scripts/run-gpc-benchmark.sh
```

Or on GPC with env vars set:

```bash
export BENCHMARK_API_URL=http://localhost:8000
export DEEPGRAM_API_KEY=<from-secrets>
export ELEVENLABS_API_KEY=<from-secrets>
./benchmarks/scripts/run-gpc-benchmark.sh
```

Uses `benchmarks/configs/component-benchmark.yaml` — **5 reps**, **2 configs**, **text + voice**.

---

## OSS-only run (if OpenAI quota is broken)

Create a quick single-config run using only Ollama + Deepgram:

```bash
cd ~/Documents/GitHub/amos2026ss04-taskorbit-conversational-agent

set -a && source backend/.env && set +a
export BENCHMARK_API_URL=http://localhost:8000
export PYTHONPATH=benchmarks/runner

mkdir -p benchmarks/results/oss-only/component

python3 benchmarks/runner/run_component_benchmark.py \
  --config benchmarks/configs/component-benchmark-smoke.yaml \
  --paths text \
  --results-dir benchmarks/results/oss-only/component
```

Then temporarily edit `component-benchmark-smoke.yaml` to keep only the `oss-ollama-deepgram-deepgram` config block (needs ≥2 configs for validation — or use both configs and ignore cloud failures in the report).

---

## Paste results into wiki

After a successful live run, copy numbers from the report into:

`Documentation/component-benchmarking.md` → **GPC results** table

Example row:

| Config | Avg total text (ms) | Avg total voice (ms) | Tool reliability | Recommendation |
|--------|---------------------|----------------------|------------------|----------------|
| `oss-ollama-deepgram-deepgram` | 22100.4 | — | 91.7% | ✓ recommended |

---

## Quick command cheat sheet

```bash
# Health check
curl http://localhost:8000/health

# Live text (smoke)
./benchmarks/scripts/run-local-demo.sh text

# Live voice
./benchmarks/scripts/run-local-demo.sh voice

# Full GPC matrix
./benchmarks/scripts/run-gpc-benchmark.sh

# View report
cat benchmarks/results/demo-*/component-benchmark-report.txt
```

---

## Troubleshooting

**Script says backend not reachable**  
→ Start uvicorn in Terminal 1.

**All cloud rows `error`, oss rows `success`**  
→ OpenAI quota issue. OSS results are still valid for demo.

**Run takes forever**  
→ Normal for multi-turn prompts + Ollama. Use smoke config (`component-benchmark-smoke.yaml`) not full 5-rep config.

**Keys show `missing` in script output**  
→ Fill in `backend/.env` and re-run.

---

## Related docs

- Demo (dry-run): `Documentation/component-benchmarking-demo.md`
- Full runbook: `Documentation/component-benchmarking.md`
- Handoff status: `Documentation/issue-68-component-benchmarking-handoff.md`
