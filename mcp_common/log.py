"""Stderr logging setup shared by the servers.

Named `log` rather than `logging` so `import logging` inside this package keeps
resolving to the standard library without a reader having to think about it.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Sequence
from typing import TextIO

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DEFAULT_DATEFMT = "%H:%M:%S"
#: The MCP SDK is chatty at DEBUG and drowns the service's own lines.
DEFAULT_QUIET_LOGGERS = ("mcp",)


def setup_logging(
    name: str,
    *,
    level: str | None = None,
    quiet_loggers: Sequence[str] = DEFAULT_QUIET_LOGGERS,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure logging to stderr and return the service logger.

    Everything goes to stderr: stdout has to stay clean for the MCP stdio transport.
    Level resolution is `level` argument > LOG_LEVEL env > INFO. Callers that want
    DEBUG in production set LOG_LEVEL rather than hardcoding it.
    """
    stream = stream if stream is not None else sys.stderr
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    resolved = (level or os.environ.get("LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=resolved,
        format=DEFAULT_FORMAT,
        datefmt=DEFAULT_DATEFMT,
        stream=stream,
    )
    for quiet in quiet_loggers:
        logging.getLogger(quiet).setLevel(logging.WARNING)

    service_logger = logging.getLogger(name)
    service_logger.setLevel(resolved)
    return service_logger
