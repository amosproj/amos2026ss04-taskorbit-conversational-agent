"""Tool implementations exposed to the LLM.

Internal adapters that the orchestration layer can invoke after the
user confirms an action. Tool definitions live here, side effects (HTTP
calls, DB writes) are delegated to integrations/.

Implementation is owned by downstream feature tickets.
"""
