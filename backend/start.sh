#!/usr/bin/env bash
set -e

echo "Running database migrations..."
poetry run alembic upgrade head

echo "Starting API server..."
exec poetry run taskorbit-api --host 0.0.0.0 --port 8000 --reload
