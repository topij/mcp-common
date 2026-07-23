"""Fail-closed authentication for the MCP SSE surface.

Cloudflare Access fronts these servers, but the apps themselves never checked a
credential — anything that reached the port was served. This middleware adds the
in-app check so a tunnel misconfiguration, a published port, or a future re-expose is
not immediately catastrophic (topij/brain#9).

Two properties are deliberate:

* **Raw ASGI, not BaseHTTPMiddleware.** Starlette's BaseHTTPMiddleware buffers the
  response body, which breaks the streaming SSE transport this is guarding.
* **Fails closed by construction.** Building an AuthMiddleware with no verifiers
  raises, so an unset env var cannot silently downgrade the guard to a pass-through —
  the process refuses to start instead.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:  # pragma: no cover - typing only
    from mcp_common.settings import CommonSettings

logger = logging.getLogger("mcp_common.auth")

#: The FastMCP SSE transport surface: the event stream plus the client's POST channel.
DEFAULT_PROTECTED_PREFIXES = ("/sse", "/messages")
#: Readiness checks stay open so container/uptime probes work without a credential.
DEFAULT_EXEMPT_PATHS = ("/health",)


class AuthConfigError(RuntimeError):
    """The auth surface was configured in a way that would not actually guard it."""


@runtime_checkable
class Verifier(Protocol):
    """Verifies a request's credentials from its headers."""

    name: str

    async def verify(self, headers: Mapping[str, str]) -> bool: ...


class SharedSecretVerifier:
    """Accepts a pre-shared key, presented as a header or a bearer token."""

    name = "shared-secret"

    def __init__(
        self,
        secret: str,
        *,
        header: str = "x-mcp-key",
        allow_bearer: bool = True,
    ) -> None:
        if not secret:
            raise AuthConfigError("shared-secret verifier requires a non-empty secret")
        self._secret = secret.encode("utf-8")
        self._header = header.lower()
        self._allow_bearer = allow_bearer

    async def verify(self, headers: Mapping[str, str]) -> bool:
        presented = headers.get(self._header)
        if presented is None and self._allow_bearer:
            scheme, _, token = headers.get("authorization", "").partition(" ")
            if scheme.lower() == "bearer":
                presented = token.strip()
        if not presented:
            return False
        # Compare as bytes: compare_digest rejects non-ASCII str, and a client can put
        # anything in a header.
        return hmac.compare_digest(presented.encode("utf-8"), self._secret)


class CloudflareAccessVerifier:
    """Validates the `Cf-Access-Jwt-Assertion` JWT that Cloudflare Access injects.

    Requires the `cloudflare` extra (PyJWT + cryptography). Signature, issuer,
    audience, and expiry are all checked — a token minted for a *different*
    application in the same Cloudflare team is rejected by the audience check.
    """

    name = "cloudflare-access"
    HEADER = "cf-access-jwt-assertion"

    def __init__(
        self,
        team_domain: str,
        audience: str,
        *,
        jwks_ttl: int = 3600,
        jwks_url: str | None = None,
    ) -> None:
        if not team_domain:
            raise AuthConfigError("cloudflare-access verifier requires a team domain")
        if not audience:
            raise AuthConfigError(
                "cloudflare-access verifier requires an application audience (AUD) tag; "
                "without it any token from the team would be accepted"
            )
        self.issuer = _normalise_team_domain(team_domain)
        self.audience = audience
        self._jwks_url = jwks_url or f"{self.issuer}/cdn-cgi/access/certs"
        self._jwks_ttl = jwks_ttl
        self._jwk_client = None

    def _get_jwk_client(self):
        if self._jwk_client is None:
            try:
                from jwt import PyJWKClient
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise AuthConfigError(
                    "CloudflareAccessVerifier needs the 'cloudflare' extra "
                    "(pip install 'mcp-common[cloudflare]')"
                ) from exc
            self._jwk_client = PyJWKClient(
                self._jwks_url, cache_keys=True, lifespan=self._jwks_ttl
            )
        return self._jwk_client

    def _verify_sync(self, token: str) -> None:
        import jwt

        signing_key = self._get_jwk_client().get_signing_key_from_jwt(token)
        jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=self.audience,
            issuer=self.issuer,
            options={"require": ["exp", "iat", "aud", "iss"]},
        )

    async def verify(self, headers: Mapping[str, str]) -> bool:
        token = headers.get(self.HEADER)
        if not token:
            return False
        try:
            # JWKS fetch and signature verification are blocking; keep them off the loop.
            await asyncio.to_thread(self._verify_sync, token)
        except Exception as exc:
            logger.warning("Cloudflare Access JWT rejected: %s", type(exc).__name__)
            return False
        return True


def _normalise_team_domain(team_domain: str) -> str:
    """Accept `example-team`, `example-team.cloudflareaccess.com`, or a full https URL."""
    value = team_domain.strip().rstrip("/")
    for prefix in ("https://", "http://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    if "." not in value:
        value = f"{value}.cloudflareaccess.com"
    return f"https://{value}"


def _headers(scope: Scope) -> dict[str, str]:
    return {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in scope.get("headers", [])
    }


class AuthMiddleware:
    """Guards `protected_prefixes` behind at least one verifier.

    Verifiers are tried in order; the first to accept lets the request through.
    """

    def __init__(
        self,
        app: ASGIApp,
        verifiers: Iterable[Verifier],
        *,
        protected_prefixes: Sequence[str] = DEFAULT_PROTECTED_PREFIXES,
        exempt_paths: Sequence[str] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        resolved = tuple(verifiers)
        if not resolved:
            raise AuthConfigError(
                "AuthMiddleware requires at least one verifier — refusing to start with "
                "an unguarded MCP surface. Set the access-key env var (MCP_ACCESS_KEY by "
                "default), or CF_ACCESS_TEAM_DOMAIN plus CF_ACCESS_AUD, or leave the "
                "middleware off deliberately."
            )
        self._app = app
        self._verifiers = resolved
        self._protected = tuple(protected_prefixes)
        self._exempt = frozenset(exempt_paths)

    def is_protected(self, path: str) -> bool:
        if path in self._exempt:
            return False
        return any(
            path == prefix or path.startswith(prefix.rstrip("/") + "/")
            for prefix in self._protected
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self._app(scope, receive, send)
            return
        if not self.is_protected(scope.get("path", "")):
            await self._app(scope, receive, send)
            return

        headers = _headers(scope)
        for verifier in self._verifiers:
            try:
                accepted = await verifier.verify(headers)
            except Exception:
                logger.exception("verifier %s raised; treating as a rejection", verifier.name)
                accepted = False
            if accepted:
                await self._app(scope, receive, send)
                return

        # Log the path but never the headers — they carry the credential.
        logger.warning("rejected unauthenticated request to %s", scope.get("path", ""))
        await self._reject(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
        await response(scope, receive, send)


def verifiers_from_settings(
    settings: CommonSettings, *, secret_header: str = "x-mcp-key"
) -> list[Verifier]:
    """Build the verifiers the environment implies.

    Returns an empty list when nothing is configured — deliberately, so that passing
    the result straight to AuthMiddleware raises rather than silently opening the door.
    """
    verifiers: list[Verifier] = []
    if settings.cf_access_team_domain and settings.cf_access_audience:
        verifiers.append(
            CloudflareAccessVerifier(
                settings.cf_access_team_domain, settings.cf_access_audience
            )
        )
    if settings.access_key:
        verifiers.append(
            SharedSecretVerifier(settings.access_key, header=secret_header)
        )
    return verifiers


def auth_middleware_from_settings(
    app: ASGIApp,
    settings: CommonSettings,
    *,
    protected_prefixes: Sequence[str] = DEFAULT_PROTECTED_PREFIXES,
    exempt_paths: Sequence[str] = DEFAULT_EXEMPT_PATHS,
    secret_header: str = "x-mcp-key",
) -> AuthMiddleware:
    """Wrap `app` using whatever credentials `settings` carries."""
    return AuthMiddleware(
        app,
        verifiers_from_settings(settings, secret_header=secret_header),
        protected_prefixes=protected_prefixes,
        exempt_paths=exempt_paths,
    )
