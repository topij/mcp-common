"""Tests for input caps."""

from __future__ import annotations

import pytest

from mcp_common.limits import InputTooLarge, cap_text


def test_strips_surrounding_whitespace():
    assert cap_text("  padded  ", 100) == "padded"


def test_rejects_empty():
    with pytest.raises(ValueError, match="content must not be empty"):
        cap_text("", 100)


def test_rejects_whitespace_only():
    with pytest.raises(ValueError, match="content must not be empty"):
        cap_text("   \n\t ", 100)


def test_rejects_none():
    with pytest.raises(ValueError, match="content must not be empty"):
        cap_text(None, 100)


def test_allows_empty_when_not_required():
    assert cap_text("", 100, required=False) == ""


def test_field_name_appears_in_messages():
    with pytest.raises(ValueError, match="transcript must not be empty"):
        cap_text("", 100, field="transcript")


def test_rejects_over_cap():
    with pytest.raises(InputTooLarge, match=r"content too long \(max 10 chars\)"):
        cap_text("x" * 11, 10)


def test_accepts_exactly_at_cap():
    assert cap_text("x" * 10, 10) == "x" * 10


def test_cap_is_measured_after_stripping():
    # Trailing whitespace must not push an otherwise-valid payload over the limit.
    assert cap_text("x" * 10 + "      ", 10) == "x" * 10


def test_input_too_large_is_a_value_error():
    # Callers that catch ValueError (and the MCP tool-error path) keep working.
    assert issubclass(InputTooLarge, ValueError)
    with pytest.raises(ValueError):
        cap_text("x" * 11, 10)
