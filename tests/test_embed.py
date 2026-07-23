"""Tests for the embedding client."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_common.embed import EmbeddingClient, EmbeddingError
from mcp_common.settings import load_settings


def _response(vector):
    return SimpleNamespace(data=[SimpleNamespace(embedding=vector)])


def _client_with(stub) -> EmbeddingClient:
    client = EmbeddingClient(api_key="sk-test")
    client._client = stub
    return client


def test_construction_does_not_build_a_client():
    # Import-time construction must stay safe when the key arrives late.
    assert EmbeddingClient(api_key=None)._client is None


def test_missing_key_raises_a_clean_error():
    with pytest.raises(EmbeddingError, match="OPENROUTER_API_KEY is not set"):
        EmbeddingClient(api_key=None).embed("hi")


def test_embed_returns_the_vector():
    stub = MagicMock()
    stub.embeddings.create.return_value = _response([0.1, 0.2, 0.3])
    assert _client_with(stub).embed("hello") == [0.1, 0.2, 0.3]


def test_embed_strips_input():
    stub = MagicMock()
    stub.embeddings.create.return_value = _response([0.0])
    _client_with(stub).embed("  padded  ")
    assert stub.embeddings.create.call_args.kwargs["input"] == "padded"


def test_embed_uses_the_configured_model():
    stub = MagicMock()
    stub.embeddings.create.return_value = _response([0.0])
    client = EmbeddingClient(api_key="sk-test", model="custom/model")
    client._client = stub
    client.embed("hi")
    assert stub.embeddings.create.call_args.kwargs["model"] == "custom/model"


def test_upstream_failure_becomes_embedding_error():
    stub = MagicMock()
    stub.embeddings.create.side_effect = RuntimeError("connection reset")
    with pytest.raises(EmbeddingError, match="embedding service unavailable") as exc:
        _client_with(stub).embed("hello")
    assert isinstance(exc.value.__cause__, RuntimeError)


def test_failure_log_does_not_leak_input(caplog):
    stub = MagicMock()
    stub.embeddings.create.side_effect = RuntimeError("body: super secret note text")
    with caplog.at_level("ERROR", logger="mcp_common.embed"):
        with pytest.raises(EmbeddingError):
            _client_with(stub).embed("super secret note text")
    assert "super secret note text" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.asyncio
async def test_embed_async_returns_the_vector():
    stub = MagicMock()
    stub.embeddings.create.return_value = _response([1.0, 2.0])
    assert await _client_with(stub).embed_async("hello") == [1.0, 2.0]


@pytest.mark.asyncio
async def test_embed_async_propagates_embedding_error():
    stub = MagicMock()
    stub.embeddings.create.side_effect = RuntimeError("boom")
    with pytest.raises(EmbeddingError):
        await _client_with(stub).embed_async("hello")


def test_from_settings_maps_every_field():
    settings = load_settings(
        "brain",
        env={
            "OPENROUTER_API_KEY": "sk-env",
            "EMBEDDING_MODEL": "m",
            "EMBEDDING_BASE_URL": "https://example.test/v1",
            "EMBEDDING_TIMEOUT": "5.5",
        },
    )
    client = EmbeddingClient.from_settings(settings)
    assert client._api_key == "sk-env"
    assert client.model == "m"
    assert client.base_url == "https://example.test/v1"
    assert client.timeout == 5.5


def test_default_timeout_is_bounded():
    # The drift this library exists to fix: an unbounded default tied up a worker for
    # ten minutes when the upstream hung.
    assert EmbeddingClient(api_key="sk-test").timeout == 30.0
