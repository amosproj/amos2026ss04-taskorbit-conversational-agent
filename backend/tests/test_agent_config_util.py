"""Tests for agent_config_util."""

from taskorbit.agent_config_util import agent_config_from_stored_blob, logical_id_from_stored_blob


def test_logical_id_from_frontend_blob() -> None:
    blob = {"agent_id": "technical-support-agent-demo", "name": "Tech"}
    assert logical_id_from_stored_blob(blob) == "technical-support-agent-demo"


def test_agent_config_from_frontend_blob() -> None:
    blob = {
        "agent_id": "technical-support-agent-demo",
        "name": "Technical Support Agentz",
        "instructions": "I am tech support.",
        "first_message": {"type": "text", "message": "Hello from tech.", "prompt": ""},
        "stt": {"provider": "deepgram", "model": "nova-3"},
        "llm": {"provider": "openai", "model": "gpt-4o-mini"},
        "tts": {"provider": "elevenlabs", "model": "eleven_turbo_v2", "voice_id": "rachel"},
        "workflow_dependencies": [],
        "allowed_handoffs": [],
    }
    config = agent_config_from_stored_blob(blob)
    assert config.id == "technical-support-agent-demo"
    assert config.name == "Technical Support Agentz"
    assert config.persona == "I am tech support."
    assert config.greeting == "Hello from tech."


def test_agent_config_from_backend_template_blob() -> None:
    blob = {
        "id": "technical-support-agent",
        "name": "Technical Support Agent",
        "persona": "Support specialist.",
        "greeting": "Hi, tech here.",
    }
    config = agent_config_from_stored_blob(blob)
    assert config.id == "technical-support-agent"
    assert config.persona == "Support specialist."
