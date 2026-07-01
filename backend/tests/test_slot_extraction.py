"""Unit tests for slot extraction functionality."""

from unittest.mock import AsyncMock, patch

import pytest

from taskorbit.config import get_settings
from taskorbit.intent import MockIntentDetector
from taskorbit.orchestration import ConversationOrchestrator
from taskorbit.slots.extractor import SlotExtractor
from taskorbit.slots.models import SlotExtractionResult, SlotValue
from taskorbit.tools.data_extraction import DataExtractionTool
from taskorbit.types import (
    AgentConfig,
    ConversationRequest,
    LLMConfig,
    Message,
    MessageRole,
    STTConfig,
    TTSConfig,
)

# ============ MOCK LLM FUNCTION ============


async def mock_llm_fn(system_prompt: str, messages: list[Message], llm_config: LLMConfig) -> str:
    """Mock LLM that returns predefined JSON for testing."""
    return '{"caller_name": "John Doe", "email_address": "john@example.com", "phone_number": "+49123456789", "preferred_date": "2026-06-01"}'


async def mock_llm_fn_missing(
    system_prompt: str, messages: list[Message], llm_config: LLMConfig
) -> str:
    """Mock LLM that returns partial data."""
    return '{"caller_name": "John Doe", "email_address": null, "phone_number": null, "preferred_date": null}'


async def mock_llm_fn_invalid_json(
    system_prompt: str, messages: list[Message], llm_config: LLMConfig
) -> str:
    """Mock LLM that returns invalid JSON."""
    return "This is not valid JSON"


# ============ TESTS FOR SLOT EXTRACTION RESULT ============


class TestSlotExtractionResult:
    """Tests for SlotExtractionResult dataclass."""

    def test_is_complete_true_when_no_missing(self):
        """Should return True when no missing slots."""
        result = SlotExtractionResult(missing=[])
        assert result.is_complete is True

    def test_is_complete_false_when_missing_exists(self):
        """Should return False when missing slots exist."""
        result = SlotExtractionResult(missing=["caller_name", "email_address"])
        assert result.is_complete is False

    def test_to_dict_returns_filled_values(self):
        """Should convert filled slots to dictionary."""
        filled = {
            "caller_name": SlotValue(name="caller_name", value="John Doe", slot_type="string"),
            "email_address": SlotValue(
                name="email_address", value="john@example.com", slot_type="email"
            ),
        }
        result = SlotExtractionResult(filled=filled, missing=[])
        assert result.to_dict() == {"caller_name": "John Doe", "email_address": "john@example.com"}

    def test_to_dict_empty_when_no_filled(self):
        """Should return empty dict when no filled slots."""
        result = SlotExtractionResult(filled={}, missing=["caller_name"])
        assert result.to_dict() == {}


# ============ TESTS FOR SLOT EXTRACTOR ============


class TestSlotExtractor:
    """Tests for SlotExtractor class."""

    @pytest.mark.asyncio
    async def test_extract_returns_filled_slots(self):
        """Should extract and return filled slots from LLM response."""
        required_inputs = [
            {"name": "caller_name", "type": "string", "required": True},
            {"name": "email_address", "type": "email", "required": True},
            {"name": "phone_number", "type": "phone", "required": True},
            {"name": "preferred_date", "type": "date", "required": True},
        ]
        messages = [
            Message(
                role=MessageRole.USER,
                content="My name is John, email john@example.com, phone +49123456789, date June 1st",
            )
        ]
        llm_config = LLMConfig(provider="openai", model="gpt-4o-mini")

        extractor = SlotExtractor(llm_fn=mock_llm_fn, llm_config=llm_config)
        result = await extractor.extract(messages, required_inputs)

        assert "caller_name" in result.filled
        assert result.filled["caller_name"].value == "John Doe"
        assert result.filled["email_address"].value == "john@example.com"
        assert result.filled["phone_number"].value == "+49123456789"
        assert result.filled["preferred_date"].value == "2026-06-01"
        assert result.missing == []

    @pytest.mark.asyncio
    async def test_extract_returns_missing_slots(self):
        """Should detect missing slots when LLM returns null values."""
        required_inputs = [
            {"name": "caller_name", "type": "string", "required": True},
            {"name": "email_address", "type": "email", "required": True},
            {"name": "phone_number", "type": "phone", "required": True},
            {"name": "preferred_date", "type": "date", "required": True},
        ]
        messages = [Message(role=MessageRole.USER, content="My name is John")]
        llm_config = LLMConfig(provider="openai", model="gpt-4o-mini")

        extractor = SlotExtractor(llm_fn=mock_llm_fn_missing, llm_config=llm_config)
        result = await extractor.extract(messages, required_inputs)

        assert "caller_name" in result.filled
        assert len(result.missing) == 3
        assert "email_address" in result.missing
        assert "phone_number" in result.missing
        assert "preferred_date" in result.missing

    @pytest.mark.asyncio
    async def test_extract_handles_invalid_json(self):
        """Should return all slots as missing when LLM returns invalid JSON."""
        required_inputs = [
            {"name": "caller_name", "type": "string", "required": True},
            {"name": "email_address", "type": "email", "required": True},
        ]
        messages = [Message(role=MessageRole.USER, content="Hello")]
        llm_config = LLMConfig(provider="openai", model="gpt-4o-mini")

        extractor = SlotExtractor(llm_fn=mock_llm_fn_invalid_json, llm_config=llm_config)
        result = await extractor.extract(messages, required_inputs)

        assert len(result.missing) == 2
        assert "caller_name" in result.missing
        assert "email_address" in result.missing
        assert result.filled == {}

    @pytest.mark.asyncio
    async def test_extract_handles_json_with_code_fences(self):
        """Should strip markdown code fences from LLM response."""

        async def mock_llm_with_fences(system_prompt, messages, llm_config):
            return '```json\n{"caller_name": "Jane Doe"}\n```'

        required_inputs = [{"name": "caller_name", "type": "string", "required": True}]
        messages = [Message(role=MessageRole.USER, content="I'm Jane")]
        llm_config = LLMConfig(provider="openai", model="gpt-4o-mini")

        extractor = SlotExtractor(llm_fn=mock_llm_with_fences, llm_config=llm_config)
        result = await extractor.extract(messages, required_inputs)

        assert result.filled["caller_name"].value == "Jane Doe"
        assert result.missing == []


# ============ TESTS FOR INTENT DETECTION ============


class TestMockIntentDetector:
    """Tests for keyword-based intent detection."""

    def test_detects_appointment_intent(self):
        """Should return appointment intent for neutral messages."""
        detector = MockIntentDetector()
        result = detector.detect("I need to book a service appointment")
        assert result.name == "book_service_appointment"
        assert len(result.required_inputs) == 5

    def test_detects_dissatisfaction_intent(self):
        """Should return dissatisfaction intent for complaint messages."""
        detector = MockIntentDetector()
        result = detector.detect("I have a complaint about your service")
        assert result.name == "customer_dissatisfaction_inquiry"
        assert len(result.required_inputs) == 4

    def test_detects_dissatisfaction_with_keywords(self):
        """Should detect dissatisfaction from various keywords."""
        detector = MockIntentDetector()
        keywords = [
            "unhappy",
            "frustrated",
            "disappointed",
            "problem",
            "issue",
            "broken",
            "wrong",
            "bad",
            "terrible",
            "awful",
            "refund",
            "cancel",
        ]
        for keyword in keywords:
            result = detector.detect(f"I am very {keyword}")
            assert (
                result.name == "customer_dissatisfaction_inquiry"
            ), f"Failed for keyword: {keyword}"


# ============ TESTS FOR DATA EXTRACTION TOOL ============


class TestDataExtractionTool:
    """Tests for DataExtractionTool."""

    @pytest.mark.asyncio
    async def test_execute_success_with_all_parameters(self):
        """Should return success when all parameters are present."""
        tool = DataExtractionTool()
        parameters = {
            "caller_name": "John Doe",
            "email_address": "john@example.com",
            "phone_number": "+49123456789",
            "preferred_date": "2026-06-01",
        }
        result = await tool.execute(parameters)
        assert result.success is True
        assert result.data == parameters
        assert result.error == "" or result.error is None

    @pytest.mark.asyncio
    async def test_execute_fails_with_missing_parameters(self):
        """Should return error when parameters are missing."""
        tool = DataExtractionTool()
        parameters = {
            "caller_name": "John Doe",
            "email_address": None,
            "phone_number": None,
            "preferred_date": None,
        }
        result = await tool.execute(parameters)
        assert result.success is False
        assert result.error is not None
        assert "Missing" in result.error

    def test_validate_parameters_returns_true_when_all_present(self):
        """Should return True when all parameters are non-None."""
        tool = DataExtractionTool()
        parameters = {"name": "John", "email": "john@example.com"}
        assert tool.validate_parameters(parameters) is True

    def test_validate_parameters_returns_false_when_any_missing(self):
        """Should return False when any parameter is None."""
        tool = DataExtractionTool()
        parameters = {"name": "John", "email": None}
        assert tool.validate_parameters(parameters) is False


# ============ TESTS FOR ORCHESTRATOR SLOT INTEGRATION ============


class TestOrchestratorSlotIntegration:
    """Tests for orchestrator's slot extraction integration."""

    @pytest.mark.asyncio
    async def test_orchestrator_returns_missing_slots_when_incomplete(
        self, mock_good_intent: object
    ):
        """Should return missing slots when not all required slots are filled."""
        settings = get_settings()
        orchestrator = ConversationOrchestrator(settings=settings)

        with patch.object(orchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Thank you for providing your information."

            with patch.object(
                orchestrator, "_extract_slots", new_callable=AsyncMock
            ) as mock_extract:
                filled = {
                    "caller_name": SlotValue(
                        name="caller_name", value="John Doe", slot_type="string"
                    ),
                    "email_address": SlotValue(
                        name="email_address", value="john@example.com", slot_type="email"
                    ),
                }
                slot_result = SlotExtractionResult(
                    filled=filled, missing=["phone_number", "preferred_date"]
                )
                mock_extract.return_value = slot_result

                agent_config = AgentConfig(
                    id="agent-1",
                    name="Test Agent",
                    persona="Helpful",
                    greeting="Hi",
                    stt=STTConfig(),
                    llm=LLMConfig(),
                    tts=TTSConfig(),
                    tools=[],
                )

                request = ConversationRequest(
                    conversation_id="test-123",
                    agent_config=agent_config,
                    messages=[
                        Message(role=MessageRole.USER, content="I need to book an appointment")
                    ],
                )

                response = await orchestrator.process_message(request)

                assert response.extracted_slots == {
                    "caller_name": "John Doe",
                    "email_address": "john@example.com",
                }
                assert len(response.missing_slots) == 2
                assert "phone_number" in response.missing_slots
                assert "preferred_date" in response.missing_slots

    @pytest.mark.asyncio
    async def test_orchestrator_returns_extracted_slots_when_complete(
        self, mock_good_intent: object
    ):
        """Should return extracted slots when all required slots are filled."""
        settings = get_settings()
        orchestrator = ConversationOrchestrator(settings=settings)

        with patch.object(orchestrator, "_call_llm", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = "Thank you for providing your information."

            with patch.object(
                orchestrator, "_extract_slots", new_callable=AsyncMock
            ) as mock_extract:
                filled = {
                    "caller_name": SlotValue(
                        name="caller_name", value="John Doe", slot_type="string"
                    ),
                    "email_address": SlotValue(
                        name="email_address", value="john@example.com", slot_type="email"
                    ),
                    "phone_number": SlotValue(
                        name="phone_number", value="+49123456789", slot_type="phone"
                    ),
                    "preferred_date": SlotValue(
                        name="preferred_date", value="2026-06-01", slot_type="date"
                    ),
                }
                slot_result = SlotExtractionResult(filled=filled, missing=[])
                mock_extract.return_value = slot_result

                agent_config = AgentConfig(
                    id="agent-1",
                    name="Test Agent",
                    persona="Helpful",
                    greeting="Hi",
                    stt=STTConfig(),
                    llm=LLMConfig(),
                    tts=TTSConfig(),
                    tools=[],
                )

                request = ConversationRequest(
                    conversation_id="test-123",
                    agent_config=agent_config,
                    messages=[
                        Message(
                            role=MessageRole.USER,
                            content="My name is John, email john@example.com, phone +49123456789, date June 1st",
                        )
                    ],
                )

                response = await orchestrator.process_message(request)

                assert "caller_name" in response.extracted_slots
                assert response.extracted_slots["caller_name"] == "John Doe"
                assert response.extracted_slots["email_address"] == "john@example.com"
                assert len(response.missing_slots) == 0

    @pytest.mark.asyncio
    async def test_orchestrator_builds_prompt_with_slots(self):
        """Should include extracted slots in system prompt."""
        orchestrator = ConversationOrchestrator()

        agent_config = AgentConfig(
            id="agent-1",
            name="Test Agent",
            persona="Helpful assistant",
            greeting="Hi",
            stt=STTConfig(),
            llm=LLMConfig(),
            tts=TTSConfig(),
            tools=[],
        )

        filled = {
            "caller_name": SlotValue(name="caller_name", value="John Doe", slot_type="string"),
        }
        slot_result = SlotExtractionResult(filled=filled, missing=["email_address", "phone_number"])

        prompt = orchestrator._build_system_prompt(agent_config, None, slot_result)

        assert "Test Agent" in prompt
        assert "- Caller Name: John Doe" in prompt
        assert "Still need to collect: Email Address, Phone Number" in prompt


# ============ TESTS FOR EMAIL NORMALIZATION ============


from taskorbit.slots.extractor import _SLOT_VALIDATORS, _normalize_email_value  # noqa: E402


class TestNormalizeEmailValue:
    """Unit tests for _normalize_email_value."""

    def test_strips_trailing_period(self):
        assert _normalize_email_value("alice@gmail.com.") == "alice@gmail.com"

    def test_strips_trailing_comma(self):
        assert _normalize_email_value("alice@gmail.com,") == "alice@gmail.com"

    def test_strips_trailing_semicolon(self):
        assert _normalize_email_value("alice@gmail.com;") == "alice@gmail.com"

    def test_spoken_at_the_rate(self):
        assert _normalize_email_value("alice at the rate gmail dot com") == "alice@gmail.com"

    def test_spoken_standalone_at(self):
        assert _normalize_email_value("alice at gmail.com") == "alice@gmail.com"

    def test_spoken_dot(self):
        assert _normalize_email_value("alice@gmail dot com") == "alice@gmail.com"

    def test_spaces_around_at_and_dot(self):
        assert _normalize_email_value("alice @ gmail . com") == "alice@gmail.com"

    def test_partial_smart_format_trailing_period(self):
        # STT emits "@" but leaves trailing period from spoken sentence end
        assert _normalize_email_value("alice@therategmail.com.") == "alice@therategmail.com"

    def test_already_clean_passes_through_unchanged(self):
        assert _normalize_email_value("alice@gmail.com") == "alice@gmail.com"

    def test_subdomain_preserved(self):
        assert _normalize_email_value("user@mail.example.co.uk") == "user@mail.example.co.uk"

    def test_hyphenated_domain_preserved(self):
        assert (
            _normalize_email_value("first-last@company-name.com") == "first-last@company-name.com"
        )

    def test_leading_and_trailing_whitespace_stripped(self):
        assert _normalize_email_value("  alice@gmail.com  ") == "alice@gmail.com"


class TestEmailValidator:
    """Tests for the tightened email validator in _SLOT_VALIDATORS."""

    def test_valid_simple_email(self):
        assert _SLOT_VALIDATORS["email"]("alice@gmail.com") is True

    def test_valid_subdomain_email(self):
        assert _SLOT_VALIDATORS["email"]("user@mail.example.co.uk") is True

    def test_valid_hyphenated_email(self):
        assert _SLOT_VALIDATORS["email"]("first-last@company-name.com") is True

    def test_rejects_trailing_period(self):
        assert _SLOT_VALIDATORS["email"]("alice@therategmail.com.") is False

    def test_rejects_numeric_tld(self):
        assert _SLOT_VALIDATORS["email"]("alice@gmail.123") is False

    def test_rejects_no_at(self):
        assert _SLOT_VALIDATORS["email"]("alicegmail.com") is False

    def test_rejects_spaces(self):
        assert _SLOT_VALIDATORS["email"]("alice @gmail.com") is False


class TestSlotExtractorEmailNormalization:
    """Integration tests: normalized value ends up in SlotValue.value."""

    @pytest.mark.asyncio
    async def test_spoken_at_the_rate_stored_normalized(self):
        async def mock_llm(system_prompt, messages, llm_config):
            return '{"email_address": "alice at the rate gmail dot com"}'

        extractor = SlotExtractor(
            llm_fn=mock_llm,
            llm_config=LLMConfig(provider="openai", model="gpt-4o-mini"),
        )
        result = await extractor.extract(
            [Message(role=MessageRole.USER, content="my email is alice at the rate gmail dot com")],
            [{"name": "email_address", "type": "email", "required": True}],
        )
        assert "email_address" in result.filled
        assert result.filled["email_address"].value == "alice@gmail.com"
        assert result.missing == []

    @pytest.mark.asyncio
    async def test_partial_smart_format_trailing_period_stored_normalized(self):
        # STT converts "@" but leaves trailing period; extraction LLM echoes it verbatim.
        async def mock_llm(system_prompt, messages, llm_config):
            return '{"email_address": "alice@therategmail.com."}'

        extractor = SlotExtractor(
            llm_fn=mock_llm,
            llm_config=LLMConfig(provider="openai", model="gpt-4o-mini"),
        )
        result = await extractor.extract(
            [Message(role=MessageRole.USER, content="my email is alice@therategmail.com.")],
            [{"name": "email_address", "type": "email", "required": True}],
        )
        assert "email_address" in result.filled
        assert result.filled["email_address"].value == "alice@therategmail.com"
        assert result.missing == []

    @pytest.mark.asyncio
    async def test_already_clean_email_unchanged(self):
        async def mock_llm(system_prompt, messages, llm_config):
            return '{"email_address": "bob@example.org"}'

        extractor = SlotExtractor(
            llm_fn=mock_llm,
            llm_config=LLMConfig(provider="openai", model="gpt-4o-mini"),
        )
        result = await extractor.extract(
            [Message(role=MessageRole.USER, content="bob@example.org")],
            [{"name": "email_address", "type": "email", "required": True}],
        )
        assert result.filled["email_address"].value == "bob@example.org"

    @pytest.mark.asyncio
    async def test_irreparable_email_treated_as_missing(self):
        # After normalization the value is still invalid → slot stays missing.
        async def mock_llm(system_prompt, messages, llm_config):
            return '{"email_address": "notanemail"}'

        extractor = SlotExtractor(
            llm_fn=mock_llm,
            llm_config=LLMConfig(provider="openai", model="gpt-4o-mini"),
        )
        result = await extractor.extract(
            [Message(role=MessageRole.USER, content="my email is notanemail")],
            [{"name": "email_address", "type": "email", "required": True}],
        )
        assert "email_address" not in result.filled
        assert "email_address" in result.missing
