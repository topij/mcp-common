"""Input size caps applied before text reaches a billed or unbounded downstream.

Every server caps input somewhere; they had each picked a different number in a
different layer. One implementation, one message shape, per-service value.
"""

from __future__ import annotations

#: Conservative default. A service that needs a different ceiling sets it explicitly
#: (via MAX_CONTENT_CHARS) so the difference is a decision, not drift.
DEFAULT_MAX_CONTENT_CHARS = 8000


class InputTooLarge(ValueError):
    """Input exceeded the configured character cap.

    Subclasses ValueError so existing `except ValueError` / MCP tool-error handling
    keeps working unchanged.
    """


def cap_text(
    text: str | None,
    max_chars: int,
    *,
    field: str = "content",
    required: bool = True,
) -> str:
    """Strip `text`, enforce the cap, and return the cleaned value.

    Length is measured *after* stripping, so trailing whitespace never pushes an
    otherwise-valid payload over the limit.
    """
    cleaned = (text or "").strip()
    if required and not cleaned:
        raise ValueError(f"{field} must not be empty")
    if len(cleaned) > max_chars:
        raise InputTooLarge(f"{field} too long (max {max_chars} chars)")
    return cleaned
