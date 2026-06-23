"""Project-wide constants shared across layers (API, worker, etc.)."""

# Seeded development user — used by the auth stub until JWT is wired in.
# Both the HTTP dependency (api/deps.py) and the voice worker import from here
# so neither layer reaches into the other's internals.
DEV_USER_EMAIL: str = "dev@taskorbit.local"
