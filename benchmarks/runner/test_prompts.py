"""Tests for #68 benchmark prompt fixtures and agent config builders."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.runner.prompts import build_agent_config, load_prompt_set

_PROMPT_SET = Path(__file__).parent.parent / "prompts" / "component_prompts.json"
_PIPELINE = {
    "stt_provider": "deepgram",
    "stt_model": "nova-3",
    "llm_provider": "openai",
    "llm_model": "gpt-4o-mini",
    "tts_provider": "elevenlabs",
    "tts_voice_id": "CwhRBWXzGAHq8TQ4Fs17",
    "tts_model": "eleven_multilingual_v2",
}


def test_load_prompt_set_has_four_categories() -> None:
    prompts = load_prompt_set(_PROMPT_SET)
    categories = {row["category"] for row in prompts}
    assert categories == {
        "short_no_tool",
        "short_with_tool",
        "long_no_tool",
        "long_with_tool",
    }
    assert len(prompts) == 6


def test_general_inquiry_agent_has_no_tools() -> None:
    config = build_agent_config("general_inquiry", _PIPELINE)
    assert config["tools"] == []
    assert "general" in config["id"]


def test_transfer_agent_attaches_agent_transfer_tool() -> None:
    config = build_agent_config("transfer_technical_support", _PIPELINE)
    assert len(config["tools"]) == 1
    assert config["tools"][0]["type"] == "agent_transfer"
    assert config["tools"][0]["parameters"]["targets"] == ["technical_support"]


def test_appointment_booking_has_data_extraction_without_confirmation() -> None:
    config = build_agent_config("appointment_booking", _PIPELINE)
    tool = config["tools"][0]
    assert tool["type"] == "data_extraction"
    assert tool["confirmation"]["required"] is False
    param_names = [p["variable_name"] for p in tool["parameters"]["params"]]
    assert param_names == ["caller_name", "email_address", "phone_number", "preferred_date"]


def test_unknown_template_raises() -> None:
    with pytest.raises(ValueError, match="Unknown benchmark agent template"):
        build_agent_config("does-not-exist", _PIPELINE)
