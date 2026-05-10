# Taskorbit Conversational Agent (AMOS SS 2026)

Production-ready streaming voice mode built on **React + Vite + TypeScript**
(frontend), **FastAPI** (backend), and **LiveKit Cloud** (real-time
audio + Agents framework). The pipeline is

```
mic → LiveKit Cloud → AgentSession (Silero VAD → Deepgram STT
                                    → ConversationOrchestrator
                                    → ElevenLabs TTS)
    → LiveKit Cloud → speaker
```

The frontend ships a ChatGPT-style mic button: tap to record, **Stop**
mutes without committing, **Send** finalises the turn for the agent.
Real-time transcription, barge-in interrupts, auto-reconnect, and a
mic-driven waveform visualisation are all included.

## Quickstart (local development)

1. **Get LiveKit Cloud credentials** — sign up at
   [LiveKit Cloud](https://cloud.livekit.io/), create a project, and
   copy the `URL`, `API key`, and `API secret`.
2. **Get a Deepgram and an ElevenLabs key** —
   [console.deepgram.com](https://console.deepgram.com) and
   [elevenlabs.io](https://elevenlabs.io/app/settings/api-keys).
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
5. Open <http://localhost:5173>, click **Start session**, allow the
   mic prompt, then tap the mic to start a turn.

See [`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md) for module-level details, and
[`Documentation/livekit-cloud-setup.md`](Documentation/livekit-cloud-setup.md)
for the full LiveKit setup walkthrough.

## Required environment variables

| Where | Var | Notes |
|---|---|---|
| `backend/.env` | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | LiveKit Cloud project credentials. The URL is `wss://...livekit.cloud`. |
| `backend/.env` | `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL`, `DEEPGRAM_LANGUAGE` | Defaults to `nova-3` / `multi`. |
| `backend/.env` | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL` | Defaults to Rachel + `eleven_multilingual_v2`. |
| `backend/.env` | `OPENAI_API_KEY` / `GOOGLE_API_KEY` (optional) | Reserved for the upcoming real-LLM integration; the orchestrator is currently an echo stub. |
| `frontend/.env.local` | `VITE_API_URL` | Where the React app proxies `/api/*`. Defaults to `http://localhost:8000`. |

## API surface

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness check used by the pre-call diagnostics card. |
| `POST` | `/v1/livekit/token` | Mints a per-call JWT. Optional `metadata` object is JSON-encoded onto the participant for the worker to read. |
| `POST` | `/v1/conversations/process` | Text-fallback turn (orchestrator round-trip). |
| `POST` | `/v1/tts/synthesize` | ElevenLabs MP3 used only by the typed-input fallback. |

## Bonus features delivered

- **Real-time transcription** — both user STT and agent TTS captions
  stream over `lk.transcription` and render as live bubbles.
- **Interrupts** — `AgentSession` allows barge-in by default; tap the
  mic again while the agent is speaking and the agent stops.
- **Auto-reconnect** — `livekit-client` retries transient drops and
  the UI surfaces a `Reconnecting…` banner.
- **Waveform** — the mic-button row draws live frequency bars from a
  `WebAudio AnalyserNode` attached to the published mic track.

## Known limitations / out of scope

- The `ConversationOrchestrator` is an echo stub. Wiring a real LLM is
  a one-class change in `backend/src/taskorbit/orchestration/__init__.py`;
  the LiveKit pipeline does not need to change.
- Chat history is not persisted to Postgres yet (DB schema is in
  place, no writes from the orchestrator).
- The mute-AI-voice toggle and mobile-only UI polish are not in this
  iteration.
