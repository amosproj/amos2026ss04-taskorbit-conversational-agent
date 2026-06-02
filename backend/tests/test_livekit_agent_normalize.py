"""Tests for ``_normalize_text`` in ``livekit_agent.llm``.

Deepgram STT (with smart_format=True) can emit Unicode punctuation in
transcriptions — em dashes, smart quotes, etc. ``_normalize_text`` replaces
these with ASCII equivalents before the text reaches the orchestrator/LLM,
preventing UnicodeEncodeError in downstream HTTP clients.

These tests verify that:
- Formatted numbers and emails from smart_format pass through unchanged.
- Each Unicode character that Deepgram can emit is replaced correctly.
- Edge cases (empty string, whitespace-only) are handled cleanly.
"""

from __future__ import annotations

from taskorbit.livekit_agent.llm import _normalize_text

# ---------------------------------------------------------------------------
# Numbers and formatted output from Deepgram smart_format
# ---------------------------------------------------------------------------


def test_normalize_preserves_integer() -> None:
    """smart_format converts 'three two one' to '321' — must not be altered."""
    assert _normalize_text("321") == "321"


def test_normalize_preserves_decimal() -> None:
    assert _normalize_text("3.14") == "3.14"


def test_normalize_preserves_phone_number() -> None:
    assert _normalize_text("+49 123 4567890") == "+49 123 4567890"


def test_normalize_preserves_email() -> None:
    """smart_format emits 'user@example.com' — must arrive at orchestrator intact."""
    assert _normalize_text("my email is user@example.com") == "my email is user@example.com"


def test_normalize_preserves_date() -> None:
    """smart_format converts spoken dates to '05/29/2026' — must pass through."""
    assert _normalize_text("05/29/2026") == "05/29/2026"


# ---------------------------------------------------------------------------
# Unicode punctuation Deepgram can emit
# ---------------------------------------------------------------------------


def test_normalize_replaces_em_dash() -> None:
    """Em dash (—) from STT is replaced with ASCII hyphen."""
    assert _normalize_text("call me—tomorrow") == "call me-tomorrow"


def test_normalize_replaces_en_dash() -> None:
    """En dash (–) from STT is replaced with ASCII hyphen."""
    assert _normalize_text("pages 10–20") == "pages 10-20"


def test_normalize_replaces_left_single_quote() -> None:
    assert _normalize_text("‘hello") == "'hello"


def test_normalize_replaces_right_single_quote() -> None:
    """Right single quote appears in contractions like 'it’s'."""
    assert _normalize_text("it’s fine") == "it's fine"


def test_normalize_replaces_left_double_quote() -> None:
    assert _normalize_text("“hello") == '"hello'


def test_normalize_replaces_right_double_quote() -> None:
    assert _normalize_text("world”") == 'world"'


def test_normalize_replaces_all_unicode_in_one_string() -> None:
    """Real-world transcript mixing multiple Unicode punctuation types."""
    result = _normalize_text("‘it’s 3—maybe 4” items“")
    assert "‘" not in result
    assert "’" not in result
    assert "—" not in result
    assert "“" not in result
    assert "”" not in result


# ---------------------------------------------------------------------------
# Whitespace handling
# ---------------------------------------------------------------------------


def test_normalize_strips_leading_whitespace() -> None:
    assert _normalize_text("  hello") == "hello"


def test_normalize_strips_trailing_whitespace() -> None:
    assert _normalize_text("hello  ") == "hello"


def test_normalize_preserves_internal_whitespace() -> None:
    assert _normalize_text("hello world") == "hello world"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_normalize_empty_string() -> None:
    assert _normalize_text("") == ""


def test_normalize_whitespace_only_string() -> None:
    assert _normalize_text("   ") == ""


def test_normalize_plain_ascii_unchanged() -> None:
    """ASCII-only text must come out byte-for-byte identical."""
    text = "Hello, my name is John and I need help."
    assert _normalize_text(text) == text
