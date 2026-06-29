"""OAuth2 client-credentials token provider with caching and single-flight refresh.

The provider fetches an access token from the configured Halo authorisation
server, caches it, and refreshes it proactively at ~80%% of its lifetime (and on
demand when the API rejects it with a 401). Refreshes are serialised through an
:class:`asyncio.Lock` so concurrent callers never trigger a token stampede.

Secrets and tokens are never placed in log lines or exception messages.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

import httpx

from .config import Settings

# Refresh when this fraction of the token lifetime has elapsed.
_REFRESH_AT = 0.8


class HaloAuthError(Exception):
    """Raised when authentication against the Halo auth server fails.

    Carries the HTTP status but a deliberately generic, redacted message so that
    neither the client secret nor any token can leak through logs or tracebacks.
    """

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(message)


class TokenProvider:
    """Fetches and caches a client-credentials access token."""

    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._settings = settings
        self._http = http
        self._clock = clock
        self._lock = asyncio.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def _is_valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at

    async def get_token(self) -> str:
        """Return a valid access token, refreshing it if needed (single-flight)."""
        if self._is_valid():
            assert self._token is not None  # noqa: S101 - narrowing for type-checker
            return self._token
        async with self._lock:
            # Another coroutine may have refreshed while we waited for the lock.
            if self._is_valid():
                assert self._token is not None  # noqa: S101 - narrowing for type-checker
                return self._token
            return await self._refresh()

    async def invalidate(self) -> None:
        """Drop the cached token so the next call re-authenticates (used on 401)."""
        async with self._lock:
            self._token = None
            self._expires_at = 0.0

    async def _refresh(self) -> str:
        params = {"tenant": self._settings.tenant} if self._settings.tenant else None
        form = {
            "grant_type": "client_credentials",
            "client_id": self._settings.client_id,
            "client_secret": self._settings.client_secret.get_secret_value(),
            "scope": self._settings.scopes,
        }
        try:
            response = await self._http.post(
                self._settings.auth_url,
                params=params,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError:
            # Do not chain the original error: its repr can echo the request body.
            raise HaloAuthError(0, "Halo authentication request failed (network error).") from None
        else:
            return self._store_token(response)

    def _store_token(self, response: httpx.Response) -> str:
        if response.status_code != httpx.codes.OK:
            raise HaloAuthError(
                response.status_code,
                f"Halo authentication failed with status {response.status_code}.",
            )
        try:
            body = response.json()
            token = str(body["access_token"])
            expires_in = float(body.get("expires_in", 3600))
        except (ValueError, KeyError, TypeError):
            # Suppress the cause: the original error's repr could echo a fragment
            # of the auth response body.
            raise HaloAuthError(
                response.status_code, "Halo auth response was missing an access_token."
            ) from None
        self._token = token
        self._expires_at = self._clock() + expires_in * _REFRESH_AT
        return token
