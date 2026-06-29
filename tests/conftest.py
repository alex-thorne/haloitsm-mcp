"""Shared test fixtures.

All Halo network traffic is mocked with respx; no test performs real network I/O.
Imports of not-yet-relevant modules are done lazily inside fixtures so that
collecting any single test file never fails on an unrelated module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from halo_mcp.config import Settings

# Stable fake instance coordinates used across the suite.
TEST_API_URL = "https://halo.test/api"
TEST_AUTH_URL = "https://halo.test/auth/token"
TEST_TOKEN = "test-access-token"  # noqa: S105 - fake token for tests


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    """Factory for fully-populated Settings, bypassing any real .env/OS env."""

    def _make(**overrides: Any) -> Settings:
        base: dict[str, Any] = {
            "api_url": TEST_API_URL,
            "auth_url": TEST_AUTH_URL,
            "client_id": "test-client-id",
            "client_secret": "test-client-secret",
            "timeout": 5.0,
        }
        base.update(overrides)
        return Settings(_env_file=None, **base)

    return _make


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture
def stub_token() -> Any:
    """A token provider that returns a static token without any network call."""

    class _StubTokenProvider:
        def __init__(self) -> None:
            self.invalidated = 0

        async def get_token(self) -> str:
            return TEST_TOKEN

        async def invalidate(self) -> None:
            self.invalidated += 1

    return _StubTokenProvider()


@pytest.fixture
def mock_token(respx_mock: Any) -> Callable[..., Any]:
    """Register the OAuth token endpoint on respx, returning TEST_TOKEN."""

    def _register(expires_in: int = 3600) -> Any:
        return respx_mock.post(TEST_AUTH_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": TEST_TOKEN,
                    "token_type": "Bearer",
                    "expires_in": expires_in,
                },
            )
        )

    return _register
