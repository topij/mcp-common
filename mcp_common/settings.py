"""Environment-backed settings shared by the MCP servers."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from mcp_common.embed import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_TIMEOUT
from mcp_common.limits import DEFAULT_MAX_CONTENT_CHARS


@dataclass(frozen=True)
class CommonSettings:
    """The settings every server in this stack shares.

    Service-specific configuration (database URLs, vault paths, bot tokens) stays in
    the service — this is only the surface that was duplicated across all three.
    """

    service_name: str
    host: str
    port: int
    log_level: str
    max_content_chars: int
    embedding_model: str
    embedding_base_url: str
    embedding_timeout: float
    openrouter_api_key: str | None
    access_key: str | None
    cf_access_team_domain: str | None
    cf_access_audience: str | None


def _env_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


def _env_str(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    return value or None


def load_settings(
    service_name: str,
    *,
    default_host: str = "127.0.0.1",
    default_port: int = 8000,
    default_max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
    env: Mapping[str, str] | None = None,
) -> CommonSettings:
    """Read the shared settings from the environment.

    Nothing here is required at load time — a missing key surfaces as a clean error at
    the point of use (embedding, auth) rather than an import-time KeyError that takes
    the whole process down before logging is even configured.
    """
    env = os.environ if env is None else env
    return CommonSettings(
        service_name=service_name,
        host=env.get("MCP_HOST") or default_host,
        port=_env_int(env, "MCP_PORT", default_port),
        log_level=(env.get("LOG_LEVEL") or "INFO").upper(),
        max_content_chars=_env_int(env, "MAX_CONTENT_CHARS", default_max_content_chars),
        embedding_model=env.get("EMBEDDING_MODEL") or DEFAULT_MODEL,
        embedding_base_url=env.get("EMBEDDING_BASE_URL") or DEFAULT_BASE_URL,
        embedding_timeout=_env_float(env, "EMBEDDING_TIMEOUT", DEFAULT_TIMEOUT),
        openrouter_api_key=_env_str(env, "OPENROUTER_API_KEY"),
        access_key=_env_str(env, "MCP_ACCESS_KEY"),
        cf_access_team_domain=_env_str(env, "CF_ACCESS_TEAM_DOMAIN"),
        cf_access_audience=_env_str(env, "CF_ACCESS_AUD"),
    )
