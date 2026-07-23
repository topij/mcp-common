"""Tests for environment-backed settings."""

from __future__ import annotations

import pytest

from mcp_common.settings import load_settings


def test_defaults_when_env_is_empty():
    s = load_settings("brain", env={})
    assert s.service_name == "brain"
    assert s.host == "127.0.0.1"
    assert s.port == 8000
    assert s.log_level == "INFO"
    assert s.max_content_chars == 8000
    assert s.embedding_model == "openai/text-embedding-3-small"
    assert s.embedding_timeout == 30.0
    assert s.openrouter_api_key is None
    assert s.access_key is None


def test_caller_defaults_override_library_defaults():
    s = load_settings(
        "brain",
        default_host="0.0.0.0",
        default_port=8001,
        default_max_content_chars=10_000,
        env={},
    )
    assert s.host == "0.0.0.0"
    assert s.port == 8001
    assert s.max_content_chars == 10_000


def test_env_overrides_caller_defaults():
    s = load_settings(
        "brain",
        default_port=8001,
        env={"MCP_HOST": "10.0.0.5", "MCP_PORT": "9999", "MAX_CONTENT_CHARS": "512"},
    )
    assert s.host == "10.0.0.5"
    assert s.port == 9999
    assert s.max_content_chars == 512


def test_empty_env_value_falls_back_to_default():
    s = load_settings("brain", default_port=8001, env={"MCP_PORT": "", "MCP_HOST": ""})
    assert s.port == 8001
    assert s.host == "127.0.0.1"


def test_log_level_is_upper_cased():
    assert load_settings("brain", env={"LOG_LEVEL": "debug"}).log_level == "DEBUG"


def test_bad_integer_names_the_variable():
    with pytest.raises(ValueError, match="MCP_PORT must be an integer"):
        load_settings("brain", env={"MCP_PORT": "not-a-port"})


def test_bad_float_names_the_variable():
    with pytest.raises(ValueError, match="EMBEDDING_TIMEOUT must be a number"):
        load_settings("brain", env={"EMBEDDING_TIMEOUT": "soon"})


def test_secrets_are_read_but_never_required():
    s = load_settings(
        "brain",
        env={
            "OPENROUTER_API_KEY": "sk-test",
            "MCP_ACCESS_KEY": "shhh",
            "CF_ACCESS_TEAM_DOMAIN": "example-team",
            "CF_ACCESS_AUD": "aud-tag",
        },
    )
    assert s.openrouter_api_key == "sk-test"
    assert s.access_key == "shhh"
    assert s.cf_access_team_domain == "example-team"
    assert s.cf_access_audience == "aud-tag"


def test_settings_are_frozen():
    s = load_settings("brain", env={})
    with pytest.raises(Exception):
        s.port = 1234  # type: ignore[misc]


def test_access_key_var_reads_from_a_custom_env_name():
    s = load_settings(
        "voice-notes",
        access_key_var="VOICE_NOTES_ACCESS_KEY",
        env={
            "VOICE_NOTES_ACCESS_KEY": "shhh",
            "MCP_ACCESS_KEY": "ignored",
        },
    )
    assert s.access_key == "shhh"


def test_access_key_var_defaults_to_mcp_access_key():
    s = load_settings("brain", env={"MCP_ACCESS_KEY": "shhh"})
    assert s.access_key == "shhh"
