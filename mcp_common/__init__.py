"""Shared primitives for the home-server MCP servers.

Factored out of brain, voice-notes, and obsidian-vault-mcp, which had each grown their
own copy of the same four concerns and drifted apart on all of them (topij/brain#24).
"""

from mcp_common.auth import (
    AuthConfigError,
    AuthMiddleware,
    CloudflareAccessVerifier,
    SharedSecretVerifier,
    Verifier,
    auth_middleware_from_settings,
    verifiers_from_settings,
)
from mcp_common.embed import EmbeddingClient, EmbeddingError
from mcp_common.framing import (
    UNTRUSTED_CONTENT_NOTE,
    frame_untrusted,
    frame_untrusted_rows,
)
from mcp_common.limits import DEFAULT_MAX_CONTENT_CHARS, InputTooLarge, cap_text
from mcp_common.log import setup_logging
from mcp_common.serve import build_app, run_sse
from mcp_common.settings import CommonSettings, load_settings

__version__ = "0.1.0"

__all__ = [
    "AuthConfigError",
    "AuthMiddleware",
    "CloudflareAccessVerifier",
    "CommonSettings",
    "DEFAULT_MAX_CONTENT_CHARS",
    "EmbeddingClient",
    "EmbeddingError",
    "InputTooLarge",
    "SharedSecretVerifier",
    "UNTRUSTED_CONTENT_NOTE",
    "Verifier",
    "__version__",
    "auth_middleware_from_settings",
    "build_app",
    "cap_text",
    "frame_untrusted",
    "frame_untrusted_rows",
    "load_settings",
    "run_sse",
    "setup_logging",
    "verifiers_from_settings",
]
