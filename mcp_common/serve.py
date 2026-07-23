"""Run a FastMCP server over SSE with middleware wrapped around it.

`FastMCP.run(transport="sse")` builds the Starlette app and the uvicorn config
internally, with no hook to insert middleware. This mirrors what it does (see
`FastMCP.run_sse_async`) while letting the caller wrap the app first — which is the
only way to get an auth guard in front of the SSE surface.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from starlette.types import ASGIApp

#: Something that takes the app and returns a wrapped app.
MiddlewareFactory = Callable[[ASGIApp], ASGIApp]


def build_app(
    mcp: Any,
    *,
    middleware: Sequence[MiddlewareFactory] = (),
    mount_path: str | None = None,
) -> ASGIApp:
    """Build the FastMCP SSE app with `middleware` wrapped around it.

    Factories are applied so that the first entry ends up outermost — it sees the
    request first, which is what you want for an auth guard.
    """
    app: ASGIApp = mcp.sse_app(mount_path)
    for factory in reversed(tuple(middleware)):
        app = factory(app)
    return app


def run_sse(
    mcp: Any,
    *,
    middleware: Sequence[MiddlewareFactory] = (),
    mount_path: str | None = None,
) -> None:
    """Serve `mcp` over SSE on the host/port already configured on the FastMCP object."""
    import uvicorn

    config = uvicorn.Config(
        build_app(mcp, middleware=middleware, mount_path=mount_path),
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    uvicorn.Server(config).run()
