# TaskOrbit — frontend

React 19 + Vite 5 + TypeScript + Tailwind CSS v4 + shadcn/ui (new-york).

This package is the browser-side client for the TaskOrbit Conversational
Agent. It hosts the voice-interaction UI and the LiveKit client that
streams audio to the backend agent worker.


---

## Setup

```bash
cd frontend
cp .env.example .env.local       # adjust if the backend is not on :8000
npm install
npm run dev
```

Vite serves on <http://localhost:5173> with hot module reload. API
calls to `/api/*` are proxied to `VITE_API_URL` (default
`http://localhost:8000`), which removes the need for CORS configuration
during local development.

For voice mode to work end-to-end, both the FastAPI API **and** the
LiveKit voice-agent worker must be running on the backend side. See
[`../backend/README.md`](../backend/README.md) for the worker
commands.

---

## Voice mode architecture

The conversational chat surface (`src/components/ConversationalChat.tsx`)
drives a state machine — `idle` → `connecting` → `idle_in_call`
→ `recording` → `thinking` → `speaking` → `idle_in_call` — fed
by real LiveKit room events.

Key moving parts:

| File | Role |
|---|---|
| `hooks/useVoiceCall.ts` | Owns the call lifecycle, transcript array, token fetch. |
| `hooks/useMicRecorder.ts` | Bridges mic publish/mute on the local participant + audio levels for the waveform. |
| `hooks/useAgentTranscription.ts` | Subscribes to `lk.transcription` text streams for live captions. |
| `hooks/useConnectionStatus.ts` | Surfaces `Reconnecting` so the UI can show a banner. |
| `lib/livekitToken.ts` | POST `/api/v1/livekit/token` (optional JSON `metadata` for the worker). |
| `lib/livekitAgentMetadata.ts` | Maps UI `AgentConfig` → backend JWT metadata. |
| `components/chat/VoiceSessionBridge.tsx` | Translates LiveKit events into call-status phase changes. |
| `components/chat/InCallControls.tsx` | Mic button + Stop/Send buttons + waveform + End call. |
| `components/chat/MicButton.tsx`, `RecordingControls.tsx`, `Waveform.tsx` | Pure UI primitives. |

Audio playback for the agent's reply uses LiveKit's `RoomAudioRenderer`
— the worker publishes the ElevenLabs TTS as a remote audio track and
the renderer plays it back without any custom decoding on the
frontend. The `/v1/tts/synthesize` REST endpoint is retained only as a
fallback for the typed-input ("Use text instead") branch.

---

## Environment (voice)

| Variable | Where | Purpose |
|----------|--------|---------|
| `VITE_API_URL` | `frontend/.env.local` | Backend origin for `/api/*` proxy (e.g. `http://localhost:8000`) |
| `LIVEKIT_*` | `backend/.env` | Minted by the API; worker consumes the same values |
| `DEEPGRAM_API_KEY` | `backend/.env` | Speech-to-text in the worker |
| `ELEVENLABS_*` | `backend/.env` | Text-to-speech in the worker |

The browser receives the LiveKit WebSocket URL inside the token response — it is not a separate frontend env var.

---

## Adding shadcn components

`components.json` is committed and `lib/utils.ts` contains the `cn()`
helper, so the shadcn CLI can be used directly:

```bash
npx shadcn@latest add button
npx shadcn@latest add input
npx shadcn@latest add card
```

The CLI writes the source file into `src/components/ui/`. The
generated files are owned by the project and intended to be modified
as needed.

---

## Project layout

```
frontend/
├── package.json
├── package-lock.json            # commit this
├── vite.config.ts
├── tsconfig.json
├── tsconfig.app.json
├── tsconfig.node.json
├── components.json              # shadcn config
├── index.html
├── .env.example                 # commit this; never commit .env.local
├── Dockerfile
├── README.md
├── public/                      # static assets served at /
└── src/
    ├── main.tsx                 # React entry
    ├── App.tsx                  # Placeholder page; replaced in #19
    ├── index.css                # Tailwind v4 + shadcn tokens
    ├── vite-env.d.ts            # Typed import.meta.env
    ├── components/
    │   ├── ui/                  # shadcn components land here
    │   ├── chat/                # call surface (mic, transcript, controls)
    │   └── ConversationalChat.tsx
    ├── lib/
    │   ├── utils.ts             # cn() helper
    │   ├── livekitToken.ts      # POST /api/v1/livekit/token client
    │   ├── livekitAgentMetadata.ts  # worker JWT metadata from AgentConfig
    │   └── conversationApi.ts   # text-fallback REST client
    ├── hooks/
    │   ├── useVoiceCall.ts
    │   ├── useMicRecorder.ts
    │   ├── useAgentTranscription.ts
    │   └── useConnectionStatus.ts
    └── pages/
```

---

## Useful commands

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server with HMR |
| `npm run build` | Type-check then build for production into `dist/` |
| `npm run preview` | Serve the built bundle locally |
| `npm run lint` | ESLint over `src/` |
| `npm run format` | Prettier over `src/` |
| `npm run type-check` | `tsc --noEmit` only |

---

`package-lock.json` is the committed source of truth for resolved
versions.
