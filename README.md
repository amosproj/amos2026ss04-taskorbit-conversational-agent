# Taskorbit Conversational Agent (AMOS SS 2026)

[![Start Web Service](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml)
[![Frontend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml)
[![Backend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml)
[![Deploy to GCP](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/deploy.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/deploy.yml)

---


## Product Goals

### Product Vision

Product Vision: TaskOrbit provides a domain-independent framework for building reliable conversational AI agents through declarative workflows and structured agent orchestration. The platform enables organizations to create configurable voice and chat agents that integrate STT, LLMs, TTS, and external APIs into unified conversational workflows.
By standardizing conversational automation across different business domains, TaskOrbit helps companies reduce manual effort, streamline internal and external processes, and deploy scalable AI-driven assistants without building custom infrastructure from scratch.

### Project Mission

The mission of this project is to create an MVP for a Voice AI Agent platform. Within the given project time-frame, the team is committed to delivering a fully functional conversational interface supporting configurable single-agent and multi-agent workflows. 
Core functionality will include the integration of STT for user input, a LLM backend for conversational processing and reasoning, agent orchestration capabilities, and TTS for audio output. The primary objective of this project is to provide a reliable and extensible end-to-end conversational system through the integration of these core components.


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
| `terraform/`     | GCP Infrastructure as Code — Cloud Run, Cloud SQL, Secret Manager, IAM, and more |
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

See [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md) for module-level details, [`Documentation/livekit-cloud-setup.md`](Documentation/livekit-cloud-setup.md) for the full LiveKit setup walkthrough, and [`Documentation/llm-providers.md`](Documentation/llm-providers.md) for the LLM provider abstraction, error taxonomy, and metric labels.

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

Three quality-gate workflows run on every push and pull request. A fourth deploys to GCP automatically once all three pass on `main`:

| Badge                 | Workflow file                                                                          | What it verifies                                                                           |
| --------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Start Web Service** | [`start-web-service.yml`](.github/workflows/start-web-service.yml)                    | Boots the FastAPI service and curls `/health`; runs `npm run build` for the frontend       |
| **Frontend Linting**  | [`frontend-lint.yml`](.github/workflows/frontend-lint.yml)                            | `npm ci` → ESLint → Prettier `--check`                                                     |
| **Backend Linting**   | [`backend-lint.yml`](.github/workflows/backend-lint.yml)                              | `poetry install` → `ruff check` → `ruff format --check` → `pytest`                        |
| **Deploy to GCP**     | [`deploy.yml`](.github/workflows/deploy.yml)                                          | Builds Docker images, pushes to Artifact Registry, deploys to Cloud Run (runs after all three above pass) |

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
