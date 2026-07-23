"""Tests for the SSE auth middleware and its verifiers."""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from mcp_common.auth import (
    AuthConfigError,
    AuthMiddleware,
    CloudflareAccessVerifier,
    SharedSecretVerifier,
    _normalise_team_domain,
    auth_middleware_from_settings,
    verifiers_from_settings,
)
from mcp_common.settings import load_settings

SECRET = "correct-horse-battery-staple"


# ---------------------------------------------------------------------------
# Fail-closed construction
# ---------------------------------------------------------------------------


def test_middleware_refuses_to_start_without_a_verifier():
    # The whole point: an unset env var must not silently become a pass-through.
    with pytest.raises(AuthConfigError, match="at least one verifier"):
        AuthMiddleware(_inner_app(), [])


def test_from_settings_refuses_when_nothing_is_configured():
    with pytest.raises(AuthConfigError):
        auth_middleware_from_settings(_inner_app(), load_settings("brain", env={}))


def test_shared_secret_verifier_rejects_an_empty_secret():
    with pytest.raises(AuthConfigError, match="non-empty secret"):
        SharedSecretVerifier("")


def test_cloudflare_verifier_requires_an_audience():
    # Without AUD, any token minted for any app in the team would be accepted.
    with pytest.raises(AuthConfigError, match="audience"):
        CloudflareAccessVerifier("example-team", "")


def test_cloudflare_verifier_requires_a_team_domain():
    with pytest.raises(AuthConfigError, match="team domain"):
        CloudflareAccessVerifier("", "aud")


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "protected"),
    [
        ("/sse", True),
        ("/sse/", True),
        ("/sse/stream", True),
        ("/messages/", True),
        ("/messages/abc", True),
        ("/health", False),
        ("/", False),
        ("/capture", False),
        # Not a prefix match by accident — a distinct route that merely starts with
        # the same letters stays unguarded rather than being broken.
        ("/ssex", False),
    ],
)
def test_is_protected(path, protected):
    mw = AuthMiddleware(_inner_app(), [SharedSecretVerifier(SECRET)])
    assert mw.is_protected(path) is protected


# ---------------------------------------------------------------------------
# Shared-secret verification through the middleware
# ---------------------------------------------------------------------------


def _inner_app() -> Starlette:
    async def ok(request):
        return JSONResponse({"ok": True, "path": request.url.path})

    return Starlette(
        routes=[
            Route("/sse", ok),
            Route("/health", ok),
            Route("/capture", ok, methods=["GET", "POST"]),
            Route("/messages/{rest:path}", ok, methods=["GET", "POST"]),
        ]
    )


def _client(**kwargs) -> TestClient:
    verifiers = kwargs.pop("verifiers", None) or [SharedSecretVerifier(SECRET)]
    return TestClient(AuthMiddleware(_inner_app(), verifiers, **kwargs))


def test_protected_path_rejects_a_request_with_no_credential():
    response = _client().get("/sse")
    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


def test_protected_path_rejects_a_wrong_secret():
    assert _client().get("/sse", headers={"x-mcp-key": "nope"}).status_code == 401


def test_protected_path_accepts_the_header():
    response = _client().get("/sse", headers={"x-mcp-key": SECRET})
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_protected_path_accepts_a_bearer_token():
    response = _client().get("/sse", headers={"authorization": f"Bearer {SECRET}"})
    assert response.status_code == 200


def test_bearer_scheme_is_case_insensitive():
    response = _client().get("/sse", headers={"authorization": f"bearer {SECRET}"})
    assert response.status_code == 200


def test_non_bearer_authorization_is_rejected():
    response = _client().get("/sse", headers={"authorization": f"Basic {SECRET}"})
    assert response.status_code == 401


def test_message_channel_is_guarded_too():
    # The POST channel carries the actual tool calls; guarding only /sse would be
    # security theatre.
    assert _client().post("/messages/x").status_code == 401
    assert (
        _client().post("/messages/x", headers={"x-mcp-key": SECRET}).status_code == 200
    )


def test_health_stays_open():
    response = _client().get("/health")
    assert response.status_code == 200


def test_unprotected_route_is_untouched():
    assert _client().get("/capture").status_code == 200


@pytest.mark.asyncio
async def test_non_ascii_credential_does_not_crash():
    # compare_digest rejects non-ASCII str, and ASGI hands us headers decoded as
    # latin-1, so a raw client can put one there. Tested at the verifier: httpx
    # refuses to *send* a non-ASCII header, so it can't be reached through TestClient.
    verifier = SharedSecretVerifier(SECRET)
    assert await verifier.verify({"x-mcp-key": "pässwörd"}) is False


def test_custom_header_name():
    verifier = SharedSecretVerifier(SECRET, header="x-brain-key")
    client = TestClient(AuthMiddleware(_inner_app(), [verifier]))
    assert client.get("/sse", headers={"x-brain-key": SECRET}).status_code == 200
    assert client.get("/sse", headers={"x-mcp-key": SECRET}).status_code == 401


def test_bearer_can_be_disabled():
    verifier = SharedSecretVerifier(SECRET, allow_bearer=False)
    client = TestClient(AuthMiddleware(_inner_app(), [verifier]))
    assert (
        client.get("/sse", headers={"authorization": f"Bearer {SECRET}"}).status_code
        == 401
    )


def test_custom_protected_prefixes():
    client = _client(protected_prefixes=("/capture",))
    assert client.get("/capture").status_code == 401
    assert client.get("/sse").status_code == 200


def test_a_raising_verifier_is_treated_as_a_rejection():
    class Exploding:
        name = "exploding"

        async def verify(self, headers):
            raise RuntimeError("jwks unreachable")

    client = TestClient(AuthMiddleware(_inner_app(), [Exploding()]))
    assert client.get("/sse").status_code == 401


def test_first_accepting_verifier_wins():
    class AlwaysNo:
        name = "no"

        async def verify(self, headers):
            return False

    client = TestClient(
        AuthMiddleware(_inner_app(), [AlwaysNo(), SharedSecretVerifier(SECRET)])
    )
    assert client.get("/sse", headers={"x-mcp-key": SECRET}).status_code == 200


def test_rejection_log_does_not_include_the_credential(caplog):
    with caplog.at_level("WARNING", logger="mcp_common.auth"):
        _client().get("/sse", headers={"x-mcp-key": "leaked-value"})
    assert "leaked-value" not in caplog.text
    assert "/sse" in caplog.text


# ---------------------------------------------------------------------------
# Non-HTTP scopes, driven at the ASGI level (TestClient only runs the lifespan
# when used as a context manager, and cannot open a raw websocket here)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_passes_straight_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    mw = AuthMiddleware(app, [SharedSecretVerifier(SECRET)])
    await mw({"type": "lifespan"}, _noop_receive, _collect(None))
    assert seen == ["lifespan"]


@pytest.mark.asyncio
async def test_unauthenticated_websocket_is_closed_not_upgraded():
    reached = []

    async def app(scope, receive, send):
        reached.append(scope["path"])

    sent = []
    mw = AuthMiddleware(app, [SharedSecretVerifier(SECRET)])
    await mw(
        {"type": "websocket", "path": "/sse", "headers": []},
        _noop_receive,
        _collect(sent),
    )
    assert reached == [], "the guarded app must never see the connection"
    assert sent == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_authenticated_websocket_reaches_the_app():
    reached = []

    async def app(scope, receive, send):
        reached.append(scope["path"])

    mw = AuthMiddleware(app, [SharedSecretVerifier(SECRET)])
    await mw(
        {
            "type": "websocket",
            "path": "/sse",
            "headers": [(b"x-mcp-key", SECRET.encode())],
        },
        _noop_receive,
        _collect([]),
    )
    assert reached == ["/sse"]


async def _noop_receive():  # pragma: no cover - never awaited in these tests
    return {"type": "noop"}


def _collect(sink):
    async def send(message):
        if sink is not None:
            sink.append(message)

    return send


# ---------------------------------------------------------------------------
# verifiers_from_settings
# ---------------------------------------------------------------------------


def test_verifiers_empty_when_unconfigured():
    assert verifiers_from_settings(load_settings("brain", env={})) == []


def test_verifiers_include_shared_secret_when_key_is_set():
    verifiers = verifiers_from_settings(
        load_settings("brain", env={"MCP_ACCESS_KEY": SECRET})
    )
    assert [v.name for v in verifiers] == ["shared-secret"]


def test_verifiers_include_cloudflare_when_both_vars_are_set():
    verifiers = verifiers_from_settings(
        load_settings(
            "brain",
            env={
                "CF_ACCESS_TEAM_DOMAIN": "example-team",
                "CF_ACCESS_AUD": "aud-tag",
                "MCP_ACCESS_KEY": SECRET,
            },
        )
    )
    assert [v.name for v in verifiers] == ["cloudflare-access", "shared-secret"]


def test_cloudflare_needs_both_vars_to_activate():
    verifiers = verifiers_from_settings(
        load_settings("brain", env={"CF_ACCESS_TEAM_DOMAIN": "example-team"})
    )
    assert verifiers == []


def test_verifiers_from_settings_honours_a_custom_secret_header():
    settings = load_settings("brain", env={"MCP_ACCESS_KEY": SECRET})
    verifiers = verifiers_from_settings(settings, secret_header="x-brain-key")
    client = TestClient(AuthMiddleware(_inner_app(), verifiers))
    assert client.get("/sse", headers={"x-brain-key": SECRET}).status_code == 200
    assert client.get("/sse", headers={"x-mcp-key": SECRET}).status_code == 401


def test_auth_middleware_from_settings_honours_a_custom_secret_header():
    settings = load_settings("brain", env={"MCP_ACCESS_KEY": SECRET})
    middleware = auth_middleware_from_settings(
        _inner_app(), settings, secret_header="x-brain-key"
    )
    client = TestClient(middleware)
    assert client.get("/sse", headers={"x-brain-key": SECRET}).status_code == 200
    assert client.get("/sse", headers={"x-mcp-key": SECRET}).status_code == 401


# ---------------------------------------------------------------------------
# Cloudflare Access JWT verification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("example-team", "https://example-team.cloudflareaccess.com"),
        ("example-team.cloudflareaccess.com", "https://example-team.cloudflareaccess.com"),
        ("https://example-team.cloudflareaccess.com", "https://example-team.cloudflareaccess.com"),
        ("https://example-team.cloudflareaccess.com/", "https://example-team.cloudflareaccess.com"),
        ("  example-team  ", "https://example-team.cloudflareaccess.com"),
    ],
)
def test_normalise_team_domain(given, expected):
    assert _normalise_team_domain(given) == expected


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def cf_verifier(rsa_key):
    verifier = CloudflareAccessVerifier("example-team", "aud-tag")

    class _Key:
        key = rsa_key.public_key()

    class _JWKClient:
        def get_signing_key_from_jwt(self, token):
            return _Key()

    verifier._jwk_client = _JWKClient()
    return verifier


def _token(rsa_key, **overrides):
    now = dt.datetime.now(dt.timezone.utc)
    claims = {
        "iss": "https://example-team.cloudflareaccess.com",
        "aud": "aud-tag",
        "iat": now,
        "exp": now + dt.timedelta(minutes=5),
        "email": "user@example.test",
    }
    claims.update(overrides)
    return jwt.encode(claims, rsa_key, algorithm="RS256")


@pytest.mark.asyncio
async def test_valid_cf_token_is_accepted(cf_verifier, rsa_key):
    headers = {CloudflareAccessVerifier.HEADER: _token(rsa_key)}
    assert await cf_verifier.verify(headers) is True


@pytest.mark.asyncio
async def test_missing_cf_header_is_rejected(cf_verifier):
    assert await cf_verifier.verify({}) is False


@pytest.mark.asyncio
async def test_cf_token_for_another_application_is_rejected(cf_verifier, rsa_key):
    # Same Cloudflare team, different app — the audience check is what stops this.
    headers = {CloudflareAccessVerifier.HEADER: _token(rsa_key, aud="someone-elses-app")}
    assert await cf_verifier.verify(headers) is False


@pytest.mark.asyncio
async def test_expired_cf_token_is_rejected(cf_verifier, rsa_key):
    past = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    headers = {
        CloudflareAccessVerifier.HEADER: _token(
            rsa_key, iat=past, exp=past + dt.timedelta(minutes=5)
        )
    }
    assert await cf_verifier.verify(headers) is False


@pytest.mark.asyncio
async def test_cf_token_from_another_issuer_is_rejected(cf_verifier, rsa_key):
    headers = {
        CloudflareAccessVerifier.HEADER: _token(
            rsa_key, iss="https://evil.cloudflareaccess.com"
        )
    }
    assert await cf_verifier.verify(headers) is False


@pytest.mark.asyncio
async def test_cf_token_signed_by_the_wrong_key_is_rejected(cf_verifier):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    headers = {CloudflareAccessVerifier.HEADER: _token(other_key)}
    assert await cf_verifier.verify(headers) is False


@pytest.mark.asyncio
async def test_garbage_cf_token_is_rejected(cf_verifier):
    assert await cf_verifier.verify({CloudflareAccessVerifier.HEADER: "not-a-jwt"}) is False


@pytest.mark.asyncio
async def test_unsigned_cf_token_is_rejected(cf_verifier, rsa_key):
    # alg=none must never be honoured.
    now = dt.datetime.now(dt.timezone.utc)
    forged = jwt.encode(
        {
            "iss": "https://example-team.cloudflareaccess.com",
            "aud": "aud-tag",
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        key="",
        algorithm="none",
    )
    assert await cf_verifier.verify({CloudflareAccessVerifier.HEADER: forged}) is False
