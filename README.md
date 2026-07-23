# mcp-common

Shared primitives for the home-server MCP servers — [brain](https://github.com/topij/brain),
[mcp-voice-notes](https://github.com/topij/mcp-voice-notes), and
[obsidian-vault-mcp](https://github.com/topij/obsidian-vault-mcp).

Each of those had grown its own copy of the same four concerns, and they had drifted:

| Concern | brain | voice-notes | obsidian |
| --- | --- | --- | --- |
| Input cap | 8 000 chars | 10 000 chars | none |
| Embedding timeout | 30 s | SDK default (600 s + retries) | — |
| Untrusted-content framing | yes | no | no |
| In-app auth on `/sse` | no | no | no |

Fixing any of those meant fixing it three times, and in practice it got fixed once.

## Install

```toml
# pyproject.toml
dependencies = [
    "mcp-common @ git+https://github.com/topij/mcp-common@v0.1.0",
]
```

`uv.lock` pins the resolved commit, so builds stay reproducible. To move a server to a
new version, bump the tag and `uv lock --upgrade-package mcp-common`.

The Cloudflare Access verifier needs an extra:

```toml
dependencies = [
    "mcp-common[cloudflare] @ git+https://github.com/topij/mcp-common@v0.1.0",
]
```

## What's in it

### `settings` — one env surface

```python
from mcp_common import load_settings

settings = load_settings("brain", default_host="0.0.0.0", default_port=8001)
```

Reads `MCP_HOST`, `MCP_PORT`, `LOG_LEVEL`, `MAX_CONTENT_CHARS`, `EMBEDDING_MODEL`,
`EMBEDDING_BASE_URL`, `EMBEDDING_TIMEOUT`, `OPENROUTER_API_KEY`, `MCP_ACCESS_KEY`,
`CF_ACCESS_TEAM_DOMAIN`, `CF_ACCESS_AUD`. Nothing is required at load time — a missing
secret surfaces as a clean error where it's used, not as an import-time `KeyError`
before logging is even configured.

Service-specific config (database URLs, vault paths, bot tokens) stays in the service.

### `limits` — input caps

```python
from mcp_common import cap_text

content = cap_text(raw, settings.max_content_chars)              # ValueError if empty
query = cap_text(raw, settings.max_content_chars, field="query") # InputTooLarge if over
```

`InputTooLarge` subclasses `ValueError`, so existing handling keeps working. Length is
measured after stripping.

### `framing` — untrusted-content delimiters

```python
from mcp_common import UNTRUSTED_CONTENT_NOTE, frame_untrusted_rows

@mcp.tool()
async def brain_search(query: str) -> list[dict]:
    """Semantic search across all thoughts.

    {UNTRUSTED_CONTENT_NOTE}
    """
    return frame_untrusted_rows(await search(query))
```

Stored content is user-authored and reaches these servers through Telegram, HTTP capture,
and folder sync — so returning it to a model holding higher-agency tools is an indirect
prompt-injection vector.

**The delimiter carries a per-response random nonce:**

```
<untrusted_user_content-3f9a2c1e8b4d5a60>
...stored content...
</untrusted_user_content-3f9a2c1e8b4d5a60>
```

A fixed delimiter isn't enough. Content containing the literal closing tag ends the block
early, and everything after it reads as trusted narration — the breakout in
[brain#6](https://github.com/topij/brain/issues/6). The nonce is generated fresh per call,
after the content is already known, and verified absent from the payload before use, so
stored content can't close a block whose nonce it couldn't predict.

### `embed` — OpenRouter embedding client

```python
from mcp_common import EmbeddingClient, EmbeddingError

embedder = EmbeddingClient.from_settings(settings)
vector = await embedder.embed_async(text)   # runs off the event loop thread
```

Bounded timeout by default (30 s). Failures raise `EmbeddingError` rather than a raw SDK
exception that becomes a 500 several layers up. Client construction is lazy, so importing
a module that builds one stays safe in tests and in containers whose secrets arrive late.
Failure logs record the exception *type*, never the input — SDK errors can echo the
request body, and the request body is the user's note.

### `auth` — fail-closed SSE guard

```python
from mcp_common import auth_middleware_from_settings, run_sse

run_sse(mcp, middleware=[lambda app: auth_middleware_from_settings(app, settings)])
```

Guards `/sse` and `/messages` (the POST channel carries the actual tool calls — guarding
only the event stream would be theatre). `/health` stays open for probes.

Accepts either a Cloudflare Access JWT (`Cf-Access-Jwt-Assertion`, verified against the
team JWKS with issuer, **audience**, and expiry checked) or a pre-shared key
(`x-mcp-key` header or `Authorization: Bearer`, compared in constant time).

Two deliberate properties:

- **Raw ASGI, not `BaseHTTPMiddleware`** — the latter buffers response bodies, which
  breaks the streaming SSE transport this exists to guard.
- **Fails closed by construction** — `AuthMiddleware` with zero verifiers *raises*. An
  unset env var can't silently downgrade the guard to a pass-through; the process refuses
  to start instead.

### `serve` — SSE with middleware

`FastMCP.run(transport="sse")` builds the Starlette app and uvicorn config internally with
no hook for middleware. `run_sse()` mirrors it while letting you wrap the app first.

## Development

```sh
uv sync --extra dev
uv run pytest tests/ -v
uv run ruff check mcp_common tests
```

## License

MIT
