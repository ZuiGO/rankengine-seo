from backend.services.chat_service import (
    CHAT_FORMAT_RULE,
    FULL_SITE_PROMPT,
    GENERAL_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)


def test_format_rule_is_defined():
    assert CHAT_FORMAT_RULE
    assert "NEVER use markdown tables, pipe characters" in CHAT_FORMAT_RULE
    assert "at most 8 dash bullets" in CHAT_FORMAT_RULE
    assert "verdict sentence" in CHAT_FORMAT_RULE


def test_format_rule_in_site_system_prompt():
    assert CHAT_FORMAT_RULE in SYSTEM_PROMPT


def test_format_rule_in_general_prompt():
    assert CHAT_FORMAT_RULE in GENERAL_SYSTEM_PROMPT


def test_full_site_chat_system_includes_format_rule():
    system = SYSTEM_PROMPT + "\n\n" + FULL_SITE_PROMPT
    assert "at most 8 dash bullets" in system


def test_no_table_markup_in_prompt_examples():
    assert "|" not in SYSTEM_PROMPT