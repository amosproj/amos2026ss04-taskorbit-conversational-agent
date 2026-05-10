# Taskorbit Conversational Agent (AMOS SS 2026)

[![Start Web Service](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/start-web-service.yml)
[![Frontend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/frontend-lint.yml)
[![Backend Linting](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml/badge.svg)](https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent/actions/workflows/backend-lint.yml)

## Repository layout

| Path             | Contents                                                          |
| ---------------- | ----------------------------------------------------------------- |
| `backend/`       | Python / FastAPI orchestration layer (Poetry-managed)             |
| `frontend/`      | React 19 + Vite + TypeScript client                               |
| `schemas/`       | Shared JSON schemas used by both backend and frontend             |
| `Documentation/` | Architecture documents, runtime diagrams, team-facing guides      |
| `.github/`       | Issue templates, workflows, and shared CI actions                 |

---

## Prerequisites

Install these once on your machine:

| Tool                                                                | Version     | Used for                                          |
| ------------------------------------------------------------------- | ----------- | ------------------------------------------------- |
| [Python](https://www.python.org/downloads/)                         | **3.11**    | Backend (matches `backend/.python-version`)       |
| [Poetry](https://python-poetry.org/docs/#installation)              | **1.8.x**   | Backend dependency management                     |
| [Node.js](https://nodejs.org/) (LTS) + npm                          | **20.x**    | Frontend dev server and build                     |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/)   | latest      | One-shot stack via `docker compose up` (optional) |
| [Git](https://git-scm.com/)                                         | latest      | Version control + pre-commit hooks                |

Optional but recommended:

- A LiveKit account (free tier) — see [`Documentation/livekit-cloud-setup.md`](Documentation/livekit-cloud-setup.md).

---

## Project setup

Clone the repo, then install both halves of the stack.

```bash
git clone https://github.com/amosproj/amos2026ss04-taskorbit-conversational-agent.git
cd amos2026ss04-taskorbit-conversational-agent
```

### 1. Backend (Python / Poetry)

```bash
cd backend
cp .env.example .env                       # then fill in API keys (see below)
poetry config virtualenvs.in-project true  # one-time, keeps .venv inside backend/
poetry install --with dev                  # installs runtime + dev deps (ruff, pytest, pre-commit, …)
cd ..
```

`poetry install` reads `pyproject.toml` + `poetry.lock` and creates the
virtualenv at `backend/.venv/`.

### 2. Frontend (Node / npm)

```bash
cd frontend
cp .env.example .env.local                 # adjust if backend isn't on :8000
npm install
cd ..
```

`npm install` resolves against `package-lock.json`, which is the
committed source of truth for resolved versions.

### 3. Pre-commit hooks (one-time)

The same lint/format checks that run in CI also run on every
`git commit` via [pre-commit](https://pre-commit.com/) (config:
[`.pre-commit-config.yaml`](.pre-commit-config.yaml)). `pre-commit` is
already declared in `backend/pyproject.toml`'s dev dependencies, so a
plain `poetry install` in `backend/` is enough — no separate
`pip install` / `brew install` needed.

```bash
poetry -C backend run pre-commit install   # wires .git/hooks/pre-commit
```

After this, ruff (backend) and ESLint + Prettier (frontend) auto-fix
staged files at commit time. See
[`Documentation/ci-cd.md`](Documentation/ci-cd.md#pre-commit-hooks-recommended)
for details and bypass instructions.

---

## Environment configuration

Two env files drive local development. Both are git-ignored — only the
`.env.example` templates are committed.

| File                  | Created from                | Loaded by                              |
| --------------------- | --------------------------- | -------------------------------------- |
| `backend/.env`        | `backend/.env.example`      | FastAPI via `pydantic-settings`        |
| `frontend/.env.local` | `frontend/.env.example`     | Vite (only `VITE_*` variables exposed) |

### Backend variables (`backend/.env`)

The full annotated template lives in
[`backend/.env.example`](backend/.env.example). Key groups:

| Group       | Variables                                                                | Required for                                          |
| ----------- | ------------------------------------------------------------------------ | ----------------------------------------------------- |
| Application | `APP_ENV`, `LOG_LEVEL`, `API_HOST`, `API_PORT`                           | Always                                                |
| CORS        | `CORS_ALLOW_ORIGINS`                                                     | Always (defaults already allow the Vite dev server)   |
| Database    | `DATABASE_URL`                                                           | Always (defaults to local Postgres on `:5435`)        |
| LiveKit     | `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`                   | Voice-agent worker + `/v1/livekit/token`              |
| Deepgram    | `DEEPGRAM_API_KEY`, `DEEPGRAM_MODEL`, `DEEPGRAM_LANGUAGE`                | Speech-to-text in the voice agent                     |
| ElevenLabs  | `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `ELEVENLABS_MODEL`          | Text-to-speech in the voice agent                     |
| LLM         | `OPENAI_API_KEY` and/or `GOOGLE_API_KEY` (+ `*_MODEL`)                   | Orchestration / agent reasoning                       |

> **Minimum to boot** the API and pass `/health`: nothing — the defaults
> in `.env.example` work as-is. Provider keys are only needed when you
> exercise the voice / orchestration paths.

> **Database**: the example points at `localhost:5435` to match the
> Postgres exposed by `docker-compose.yml`. If you bring up your own
> Postgres on a different port, update `DATABASE_URL` accordingly.

### Frontend variables (`frontend/.env.local`)

Only variables prefixed with `VITE_` are exposed to the browser bundle.

| Variable           | Default                          | Used for                                    |
| ------------------ | -------------------------------- | ------------------------------------------- |
| `VITE_API_URL`     | `http://localhost:8000`          | Backend HTTP base URL (proxied via `/api/*`) |
| `VITE_LIVEKIT_URL` | `wss://your-project.livekit.cloud` | LiveKit room connection from the browser   |
| `VITE_APP_NAME`    | `TaskOrbit`                      | Window title and headings                   |

> **LiveKit URL**: must be the same as the backend's `LIVEKIT_URL`. See
> [`Documentation/livekit-cloud-setup.md`](Documentation/livekit-cloud-setup.md)
> for how to provision a free LiveKit Cloud project.

---

## Running the project

Pick the workflow that matches what you're doing.

### Option A — Docker Compose (one command, full stack)

Brings up Postgres, the FastAPI backend, and the Vite dev server with
hot reload on both sides.

```bash
docker compose up --build
```

Services after startup:

| Service  | URL                          | Notes                                  |
| -------- | ---------------------------- | -------------------------------------- |
| Frontend | <http://localhost:5173>      | Vite dev server with HMR               |
| Backend  | <http://localhost:8000>      | FastAPI; `/health`, `/docs`            |
| Postgres | `postgresql://localhost:5435` | Mapped from `:5432` inside container  |

Tear down with `docker compose down` (add `-v` to also drop the Postgres
volume).

### Option B — Run backend and frontend separately (no Docker)

Useful when you want to attach a debugger or skip the container build.

**Backend** (terminal 1):

```bash
cd backend
poetry run taskorbit-api                   # starts FastAPI on http://localhost:8000
```

**Frontend** (terminal 2):

```bash
cd frontend
npm run dev                                # starts Vite on http://localhost:5173
```

> If you skip Postgres, the API still boots and `/health` is green
> (`/health` does not touch the DB). Endpoints that hit the database
> will fail until you start a Postgres instance and point
> `DATABASE_URL` at it.

### Smoke test

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"taskorbit-backend","version":"0.1.0"}
```

Open <http://localhost:5173> for the frontend.

### Useful per-package commands

| Backend (`cd backend`)            | What it does                       |
| --------------------------------- | ---------------------------------- |
| `poetry run taskorbit-api`        | Start FastAPI on `:8000`           |
| `poetry run pytest`               | Run the test suite                 |
| `poetry run ruff check .`         | Lint                               |
| `poetry run ruff format .`        | Auto-format                        |

| Frontend (`cd frontend`)          | What it does                       |
| --------------------------------- | ---------------------------------- |
| `npm run dev`                     | Vite dev server with HMR           |
| `npm run build`                   | Type-check + production build      |
| `npm run preview`                 | Serve the built bundle locally     |
| `npm run lint`                    | ESLint over `src/`                 |
| `npm run format:check`            | Prettier `--check`                 |

For deeper per-package details, see
[`backend/README.md`](backend/README.md) and
[`frontend/README.md`](frontend/README.md).

---

## CI / CD

Three independent GitHub Actions workflows run on every push and pull
request, so each one publishes its own pass/fail badge above:

| Badge               | Workflow file                                                                  | What it verifies                                                              |
| ------------------- | ------------------------------------------------------------------------------ | ----------------------------------------------------------------------------- |
| **Start Web Service** | [`start-web-service.yml`](.github/workflows/start-web-service.yml) | Boots the FastAPI service and curls `/health`; runs `npm run build` for the frontend |
| **Frontend Linting**  | [`frontend-lint.yml`](.github/workflows/frontend-lint.yml)         | `npm ci` → ESLint → Prettier `--check`                                                |
| **Backend Linting**   | [`backend-lint.yml`](.github/workflows/backend-lint.yml)           | `poetry install` → `ruff check` → `ruff format --check` → `pytest`                    |

Each workflow is split into named stages chained with `needs:`, so a
single failing stage (e.g. *Lint* in *Backend Linting*) shows up clearly
in the GitHub Checks UI without re-running earlier stages. The full
team-facing guide — local commands, troubleshooting, and how to extend
the pipeline — lives in [`Documentation/ci-cd.md`](Documentation/ci-cd.md).

### Merging is gated on CI

The `main` branch is protected via GitHub's branch-protection settings: a
pull request can only be merged after all three CI workflows above pass
green and at least one reviewer has approved.

### Pre-commit hooks

The same lint/format checks also run on every `git commit` via
[pre-commit](https://pre-commit.com/). One-time wiring is covered in
[Project setup → step 3](#3-pre-commit-hooks-one-time); the full guide
(what runs, how to bypass, troubleshooting) is in
[`Documentation/ci-cd.md`](Documentation/ci-cd.md#pre-commit-hooks-recommended).
