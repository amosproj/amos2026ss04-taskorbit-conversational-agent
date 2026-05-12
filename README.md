# Taskorbit Conversational Agent (AMOS SS 2026)

[![Start Web Service](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml)
[![Frontend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml)
[![Backend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml)

---

## Overview

Production-ready streaming voice mode built on **React + Vite + TypeScript** (frontend), **FastAPI** (backend), and **LiveKit Cloud** (real-time audio + Agents framework). The pipeline is:

```
mic → LiveKit Cloud → AgentSession (Silero VAD → Deepgram STT
                                    → ConversationOrchestrator
                                    → ElevenLabs TTS)
    → LiveKit Cloud → speaker
```

The frontend ships a ChatGPT-style mic button: tap to record, **Stop** mutes without committing, **Send** finalises the turn for the agent. Real-time transcription, barge-in interrupts, auto-reconnect, and a mic-driven waveform visualisation are all included.

---

## Repository Layout

| Path             | Contents                                                          |
| ---------------- | ----------------------------------------------------------------- |
| `backend/`       | Python / FastAPI orchestration layer (Poetry-managed)             |
| `frontend/`      | React 19 + Vite + TypeScript client                               |
| `schemas/`       | Shared JSON schemas used by both backend and frontend             |
| `Documentation/` | Architecture documents, runtime diagrams, team-facing guides      |
| `.github/`       | Issue templates, workflows, and shared CI actions (`actions/*`)   |

---

## Quickstart (Local Development)

1. **Get LiveKit Cloud credentials** — sign up at [LiveKit Cloud](https://cloud.livekit.io/), create a project, and copy the `URL`, `API key`, and `API secret`.
2. **Get a Deepgram and an ElevenLabs key** — [console.deepgram.com](https://console.deepgram.com) and [elevenlabs.io](https://elevenlabs.io/app/settings/api-keys).
3. **Configure env**:

   ```bash
   cp backend/.env.example backend/.env             # fill in LiveKit, Deepgram, ElevenLabs
   cp frontend/.env.example frontend/.env.local
   ```

4. **Bring everything up**:

   ```bash
   docker compose up --build
   # postgres → :5435  api → :8000  worker → (no host port)  frontend → :5173
   ```

   Or run each piece directly without Docker:

   ```bash
   # terminal 1
   cd backend && poetry install && poetry run taskorbit-api
   # terminal 2
   cd backend && poetry run taskorbit-worker dev
   # terminal 3
   cd frontend && npm install && npm run dev
   ```

5. Open <http://localhost:5173>, click **Start session**, allow the mic prompt, then tap the mic to start a turn.

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) for module-level details, and [`Documentation/livekit-cloud-setup.md`](Documentation/livekit-cloud-setup.md) for the full LiveKit setup walkthrough.

---

## Required Environment Variables

| Where               | Var                                                              | Notes                                                                            |
| ------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `backend/.env`      | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`          | LiveKit Cloud project credentials. The URL is `wss://...livekit.cloud`.          |
| `backend/.env`      | `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL`, `DEEPGRAM_LANGUAGE`        | Defaults to `nova-3` / `multi`.                                                  |
| `backend/.env`      | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`  | Defaults to Rachel + `eleven_multilingual_v2`.                                   |
| `backend/.env`      | `OPENAI_API_KEY` / `GOOGLE_API_KEY` (optional)                  | Reserved for the upcoming real-LLM integration; the orchestrator is currently an echo stub. |
| `frontend/.env.local` | `VITE_API_URL`                                                 | Where the React app proxies `/api/*`. Defaults to `http://localhost:8000`.       |

---

## API Surface

| Method | Path                        | Purpose                                                      |
| ------ | --------------------------- | ------------------------------------------------------------ |
| `GET`  | `/health`                   | Liveness check used by the pre-call diagnostics card.        |
| `POST` | `/v1/livekit/token`         | Mints a per-call JWT. Optional `metadata` object is JSON-encoded onto the participant for the worker to read. |
| `POST` | `/v1/conversations/process` | Text-fallback turn (orchestrator round-trip).                |
| `POST` | `/v1/tts/synthesize`        | ElevenLabs MP3 used only by the typed-input fallback.        |

---

## CI / CD

Three independent GitHub Actions workflows run on every push and pull request, each publishing its own pass/fail badge:

| Badge                 | Workflow file                                                                          | What it verifies                                                                           |
| --------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Start Web Service** | [`start-web-service.yml`](.github/workflows/start-web-service.yml)                    | Boots the FastAPI service and curls `/health`; runs `npm run build` for the frontend       |
| **Frontend Linting**  | [`frontend-lint.yml`](.github/workflows/frontend-lint.yml)                            | `npm ci` → ESLint → Prettier `--check`                                                     |
| **Backend Linting**   | [`backend-lint.yml`](.github/workflows/backend-lint.yml)                              | `poetry install` → `ruff check` → `ruff format --check` → `pytest`                        |

Each workflow is split into named stages chained with `needs:`, so a single failing stage shows up clearly in the GitHub Checks UI. The full team-facing guide — local commands, troubleshooting, and how to extend the pipeline — lives in [`Documentation/ci-cd.md`](Documentation/ci-cd.md).

### Pre-commit Hooks

The same lint/format checks run automatically on every `git commit` via [pre-commit](https://pre-commit.com/) (config: [`.pre-commit-config.yaml`](.pre-commit-config.yaml)). `pre-commit` is already declared in `backend/pyproject.toml`'s dev dependencies, so a plain `poetry install` in `backend/` is enough to install it.

One-time setup on a fresh clone:

```bash
# 1. Install backend dev deps (this includes pre-commit).
cd backend && poetry install --with dev && cd ..

# 2. Wire the git hook (run from the repo root).
poetry -C backend run pre-commit install

# 3. Frontend hooks reuse the project's local node_modules.
cd frontend && npm install
```

After this, ruff (backend) and ESLint + Prettier (frontend) auto-fix staged files at commit time. See [`Documentation/ci-cd.md`](Documentation/ci-cd.md#pre-commit-hooks-recommended) for details and bypass instructions.

---

## Bonus Features Delivered

- **Real-time transcription** — both user STT and agent TTS captions stream over `lk.transcription` and render as live bubbles.
- **Interrupts** — `AgentSession` allows barge-in by default; tap the mic again while the agent is speaking and the agent stops.
- **Auto-reconnect** — `livekit-client` retries transient drops and the UI surfaces a `Reconnecting…` banner.
- **Waveform** — the mic-button row draws live frequency bars from a `WebAudio AnalyserNode` attached to the published mic track.

---

## Known Limitations / Out of Scope

- The `ConversationOrchestrator` is an echo stub. Wiring a real LLM is a one-class change in `backend/src/taskorbit/orchestration/__init__.py`; the LiveKit pipeline does not need to change.
- Chat history is not persisted to Postgres yet (DB schema is in place, no writes from the orchestrator).
- The mute-AI-voice toggle and mobile-only UI polish are not in this iteration.
