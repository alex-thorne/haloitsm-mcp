"""Tests for the read-only smoke test entry point."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from halo_mcp.config import Settings
from halo_mcp.smoke import run_smoke

from .conftest import TEST_API_URL, TEST_AUTH_URL


async def test_smoke_success_prints_count_and_first_page(
    make_settings: Callable[..., Settings],
    respx_mock,  # noqa: ANN001
    mock_token: Callable[..., object],
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_token()
    respx_mock.get(f"{TEST_API_URL}/Tickets").mock(
        return_value=httpx.Response(
            200,
            json={
                "record_count": 3,
                "tickets": [{"id": 1, "summary": "alpha"}, {"id": 2, "summary": "beta"}],
            },
        )
    )
    rc = await run_smoke(make_settings())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Auth OK" in out
    assert "record_count: 3" in out
    assert "alpha" in out


async def test_smoke_returns_nonzero_on_auth_failure(
    make_settings: Callable[..., Settings],
    respx_mock,  # noqa: ANN001
    capsys: pytest.CaptureFixture[str],
) -> None:
    respx_mock.post(TEST_AUTH_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_client"})
    )
    rc = await run_smoke(make_settings())
    assert rc == 1
    err = capsys.readouterr().err
    assert "test-client-secret" not in err  # never leak the secret


async def test_smoke_does_not_leak_secret_on_partial_config(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Realistic misconfig: the secret is set but a required URL/id is missing.
    # pydantic's ValidationError str echoes the raw input dict — the smoke test
    # must NOT print it verbatim, or it leaks the secret.
    for var in ("HALO_API_URL", "HALO_AUTH_URL", "HALO_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HALO_CLIENT_SECRET", "SUPERSECRETXYZ123")
    rc = await run_smoke()  # settings=None -> load from env -> ValidationError
    assert rc == 1
    captured = capsys.readouterr()
    assert "SUPERSECRETXYZ123" not in captured.err
    assert "SUPERSECRETXYZ123" not in captured.out
