"""Tests for the SSE serving helper."""

from __future__ import annotations

from types import SimpleNamespace

from mcp_common.serve import build_app


class _FakeMCP:
    """Stands in for FastMCP: build_app only needs sse_app() and settings."""

    def __init__(self):
        self.mount_path_seen = "<unset>"
        self.settings = SimpleNamespace(host="127.0.0.1", port=8001, log_level="INFO")

    def sse_app(self, mount_path=None):
        self.mount_path_seen = mount_path
        return "base-app"


def test_build_app_returns_the_bare_app_without_middleware():
    assert build_app(_FakeMCP()) == "base-app"


def test_mount_path_is_forwarded():
    mcp = _FakeMCP()
    build_app(mcp, mount_path="/mcp")
    assert mcp.mount_path_seen == "/mcp"


def test_middleware_is_applied_outermost_first():
    # The first factory must end up outermost so an auth guard sees the request first.
    order = []

    def outer(app):
        order.append("outer")
        return f"outer({app})"

    def inner(app):
        order.append("inner")
        return f"inner({app})"

    result = build_app(_FakeMCP(), middleware=[outer, inner])
    assert result == "outer(inner(base-app))"
    # Applied bottom-up, so the innermost wrapper is constructed first.
    assert order == ["inner", "outer"]
