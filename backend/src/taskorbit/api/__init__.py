"""HTTP API layer.

Hosts the FastAPI application that mints access tokens for the LiveKit
client, exposes health endpoints, and (as downstream tickets land) will
host the orchestration / chat-history / confirmation admin endpoints.

See the architecture doc for the full role of this module.
"""
