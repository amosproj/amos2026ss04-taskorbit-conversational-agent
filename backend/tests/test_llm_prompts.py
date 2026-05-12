from taskorbit.integrations.llm.prompts import with_same_language_instruction


def test_appends_instruction():
    result = with_same_language_instruction("You are a helpful assistant.")
    assert "You are a helpful assistant." in result
    assert "Respond in the same language" in result


def test_preserves_original_prompt():
    prompt = "You are a helpful assistant."
    result = with_same_language_instruction(prompt)
    assert result.startswith(prompt)


def test_separates_with_blank_line():
    prompt = "You are a helpful assistant."
    result = with_same_language_instruction(prompt)
    assert "\n\n" in result
