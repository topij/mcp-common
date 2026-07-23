"""OpenRouter-backed embedding client with a bounded timeout.

The servers had drifted here in the way that bites hardest: one bounded every call at
30s, the other used the SDK default (600s plus retries), so a hung upstream tied up a
worker for ten minutes. The timeout is a constructor argument with a sane default, and
failures surface as EmbeddingError rather than a raw SDK/network exception that becomes
a 500 several layers up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from openai import OpenAI

    from mcp_common.settings import CommonSettings

DEFAULT_MODEL = "openai/text-embedding-3-small"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 30.0

logger = logging.getLogger("mcp_common.embed")


class EmbeddingError(RuntimeError):
    """The embedding service was unreachable, unconfigured, or returned an error."""


class EmbeddingClient:
    """Lazily-constructed OpenAI-protocol embedding client.

    Construction never touches the network or requires a key, so importing a module
    that builds one at import time stays safe in tests and in a container whose
    secrets arrive late.
    """

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self._client: OpenAI | None = None

    @classmethod
    def from_settings(cls, settings: CommonSettings) -> EmbeddingClient:
        return cls(
            api_key=settings.openrouter_api_key,
            model=settings.embedding_model,
            base_url=settings.embedding_base_url,
            timeout=settings.embedding_timeout,
        )

    def _get_client(self) -> OpenAI:
        if self._client is None:
            if not self._api_key:
                raise EmbeddingError("OPENROUTER_API_KEY is not set")
            from openai import OpenAI

            self._client = OpenAI(
                base_url=self.base_url, api_key=self._api_key, timeout=self.timeout
            )
        return self._client

    def embed(self, text: str) -> list[float]:
        """Embed `text`. Blocking — use embed_async() from async code."""
        client = self._get_client()
        try:
            response = client.embeddings.create(model=self.model, input=text.strip())
        except Exception as exc:
            # Log the exception *type* at error level: SDK errors can echo the request
            # body, and the request body is the user's note.
            logger.error("embedding call failed: %s", type(exc).__name__)
            logger.debug("embedding failure detail", exc_info=True)
            raise EmbeddingError("embedding service unavailable") from exc
        return response.data[0].embedding

    async def embed_async(self, text: str) -> list[float]:
        """Embed `text` off the event loop thread."""
        return await asyncio.to_thread(self.embed, text)
