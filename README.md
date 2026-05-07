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
| `.github/`       | Issue templates, workflows, and shared CI actions (`actions/*`) |

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

### Pre-commit hooks

The same lint/format checks run automatically on every `git commit` via
[pre-commit](https://pre-commit.com/) (config:
[`.pre-commit-config.yaml`](.pre-commit-config.yaml)). `pre-commit` is
already declared in `backend/pyproject.toml`'s dev dependencies, so a
plain `poetry install` in `backend/` is enough to install it — no
separate `pip install`/`brew install` needed.

One-time setup on a fresh clone:

```bash
# 1. Install backend dev deps (this includes pre-commit).
cd backend && poetry install --with dev && cd ..

# 2. Wire the git hook (run from the repo root so pre-commit finds .pre-commit-config.yaml).
poetry -C backend run pre-commit install

# 3. Frontend hooks reuse the project's local node_modules.
cd frontend && npm install
```

After this, ruff (backend) and ESLint + Prettier (frontend) auto-fix
staged files at commit time. See
[`Documentation/ci-cd.md`](Documentation/ci-cd.md#pre-commit-hooks-recommended)
for details and bypass instructions.
