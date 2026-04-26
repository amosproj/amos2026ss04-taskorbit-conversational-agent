"""PostgreSQL access layer.

SQLAlchemy session/engine setup, models, and repository helpers.
Persists chat history, messages, confirmations, agent traces, and
tool-call results — see the architecture document.

Implementation is owned by downstream feature tickets. The dev
environment declares sqlalchemy / alembic / psycopg as dependencies
so these tickets don't need to touch pyproject.toml.
"""
