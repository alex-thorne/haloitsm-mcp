"""Async HTTP client for the Halo ITSM REST API.

Responsibilities:
* inject a bearer token (from :mod:`halo_mcp.auth`) on every request;
* refresh the token and retry once on ``401``;
* retry ``429``/``502``/``503`` with exponential backoff + jitter, honouring
  ``Retry-After`` when present, capped at a fixed number of attempts;
* raise a typed :class:`HaloAPIError` (status + parsed body) on any other
  non-2xx, never leaking the auth header;
* offset-based pagination via Halo's ``page_no``/``page_size`` + ``record_count``,
  with a hard page cap to avoid runaway loops;
* a ``post_update`` wrapper that refuses to fire without an explicit ``id``
  (Halo upserts on POST — omitting ``id`` silently creates a duplicate).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from .auth import TokenProvider
from .config import Settings
from .observability import current_request_id, get_logger, new_request_id

# Statuses Halo may return transiently; rate limits are undocumented and differ
# between self-hosted and cloud, so treat these as retryable.
_RETRY_STATUSES = frozenset({429, 502, 503})
_BACKOFF_BASE = 0.5
_BACKOFF_JITTER = 0.5
_DEFAULT_MAX_RETRIES = 4
_DEFAULT_MAX_PAGES = 1000
# Halo's REST API caps list responses at 100 rows/page regardless of the
# requested page_size; requesting more silently truncates, so we clamp to match.
HALO_MAX_PAGE_SIZE = 100

AsyncSleep = Callable[[float], Awaitable[None]]


class HaloAPIError(Exception):
    """Raised on a non-2xx Halo API response. Surfaces status + parsed body."""

    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Halo API request failed with status {status}.")


class HaloForbiddenError(HaloAPIError):
    """Raised on a 403 — typically the granted OAuth scopes omit this resource.

    Carries the request ``path`` so callers can name the resource in a
    scope-aware message without leaking the auth header or token.
    """

    def __init__(self, status: int, body: Any, path: str) -> None:
        super().__init__(status, body)
        self.path = path


class HaloClient:
    """A thin, retrying async wrapper over the Halo REST API."""

    def __init__(
        self,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        token_provider: TokenProvider | None = None,
        sleep: AsyncSleep = asyncio.sleep,
        rng: random.Random | None = None,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        max_pages: int = _DEFAULT_MAX_PAGES,
    ) -> None:
        self._settings = settings
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=settings.timeout)
        self._token_provider = token_provider or TokenProvider(settings, self._http)
        self._sleep = sleep
        self._rng = rng or random.Random()  # noqa: S311 - jitter, not crypto
        self._max_retries = max_retries
        self._max_pages = max_pages
        self._log = get_logger()

    @property
    def page_size(self) -> int:
        """Default list page size, from settings."""
        return self._settings.page_size

    @property
    def scopes(self) -> str:
        """The configured OAuth scopes (non-secret), for scope-aware errors."""
        return self._settings.scopes

    @property
    def long_timeout(self) -> float:
        """Timeout (seconds) for heavy endpoints, from settings."""
        return self._settings.long_timeout

    @property
    def base_url(self) -> str:
        """The Halo API base URL."""
        return self._settings.base_url

    async def __aenter__(self) -> HaloClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.base_url}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        url = self._url(path)
        timeout_arg: Any = httpx.USE_CLIENT_DEFAULT if timeout is None else timeout
        new_request_id()
        started = time.monotonic()
        attempt = 0
        reauthed = False
        while True:
            token = await self._token_provider.get_token()
            response = await self._http.request(
                method,
                url,
                params=params,
                json=json,
                headers={"Authorization": f"Bearer {token}"},
                timeout=timeout_arg,
            )
            status = response.status_code
            if status == httpx.codes.UNAUTHORIZED and not reauthed:
                await self._token_provider.invalidate()
                reauthed = True
                continue
            if status in _RETRY_STATUSES and attempt < self._max_retries:
                self._log_request(method, path, status, started, attempt, retry=True)
                await self._sleep(self._retry_delay(response, attempt))
                attempt += 1
                continue
            self._log_request(method, path, status, started, attempt, retry=False)
            if status >= httpx.codes.BAD_REQUEST:
                body = _parse_body(response)
                if status == httpx.codes.FORBIDDEN:
                    raise HaloForbiddenError(status, body, path)
                raise HaloAPIError(status, body)
            return response

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return float(retry_after)
            except ValueError:
                pass  # not a seconds value (e.g. an HTTP-date) -> fall back to backoff
        jitter = self._rng.uniform(0, _BACKOFF_JITTER)  # noqa: S311 - jitter, not crypto
        return _BACKOFF_BASE * (2.0**attempt) + jitter

    def _log_request(
        self, method: str, path: str, status: int, started: float, attempt: int, *, retry: bool
    ) -> None:
        level = logging.WARNING if retry or status >= httpx.codes.BAD_REQUEST else logging.INFO
        self._log.log(
            level,
            "halo request",
            extra={
                "method": method,
                "path": path,
                "status": status,
                "attempt": attempt,
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "request_id": current_request_id(),
            },
        )

    async def get(
        self, path: str, params: dict[str, Any] | None = None, *, timeout: float | None = None
    ) -> Any:
        return _parse_body(await self._request("GET", path, params=params, timeout=timeout))

    async def post(self, path: str, json: Any, *, timeout: float | None = None) -> Any:
        return _parse_body(await self._request("POST", path, json=json, timeout=timeout))

    async def post_update(
        self, path: str, payload: dict[str, Any], *, timeout: float | None = None
    ) -> Any:
        """POST an update, refusing to proceed without an explicit ``id``.

        Halo uses POST for both create and update; omitting ``id`` silently
        creates a duplicate, so we fail loudly instead.
        """
        if not payload.get("id"):
            raise ValueError(
                "update requires an explicit non-empty 'id' — Halo upserts on POST, "
                "so omitting 'id' would create a duplicate record."
            )
        return await self.post(path, json=payload, timeout=timeout)

    async def paginate(
        self,
        resource: str,
        *,
        collection_key: str,
        params: dict[str, Any] | None = None,
        page_size: int | None = None,
        max_records: int | None = None,
        timeout: float | None = None,
    ) -> list[dict[str, Any]]:
        """Walk Halo's offset pages until ``record_count`` is satisfied.

        Halo list endpoints take 1-indexed ``page_no`` + ``page_size`` and wrap
        the rows in a named ``collection_key`` alongside a ``record_count``. The
        ``pageinate`` flag (Halo's spelling) switches on server-side paging.
        """
        size = min(page_size or self._settings.page_size, HALO_MAX_PAGE_SIZE)
        records: list[dict[str, Any]] = []
        page_no = 1
        while page_no <= self._max_pages:
            page_params: dict[str, Any] = {
                **(params or {}),
                "pageinate": True,
                "page_no": page_no,
                "page_size": size,
            }
            body = await self.get(resource, params=page_params, timeout=timeout)
            rows, record_count = _extract_page(body, collection_key)
            records.extend(rows)
            if not rows:
                break
            if max_records is not None and len(records) >= max_records:
                break
            if record_count is not None and len(records) >= record_count:
                break
            page_no += 1
        return records[:max_records] if max_records is not None else records


def _extract_page(body: Any, collection_key: str) -> tuple[list[dict[str, Any]], int | None]:
    """Pull the row list and record_count out of a Halo list response.

    Halo's envelope key varies per endpoint (e.g. ``/Agent`` uses ``results``,
    not ``agents``), so when the named key is absent we fall back to the first
    list-valued field rather than silently returning nothing.
    """
    if isinstance(body, list):
        return body, None
    if isinstance(body, dict):
        rows = body.get(collection_key)
        if not isinstance(rows, list):
            rows = next((v for v in body.values() if isinstance(v, list)), [])
        record_count = body.get("record_count")
        return rows, record_count if isinstance(record_count, int) else None
    return [], None


def _parse_body(response: httpx.Response) -> Any:
    """Return the JSON body when possible, otherwise the raw text."""
    try:
        return response.json()
    except ValueError:
        return response.text
