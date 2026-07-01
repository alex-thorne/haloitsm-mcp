"""Tests for the pydantic-settings configuration contract."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from halo_mcp.config import Settings


def test_defaults_are_read_only_and_least_privilege(
    make_settings: Callable[..., Settings],
) -> None:
    s = make_settings()
    # Writes are off unless explicitly enabled.
    assert s.enable_writes is False
    # Default scopes are the least-privilege read set. Only scope names that
    # actually exist on Halo — there is no read:users or read:agents scope
    # (requesting them yields invalid_scope); that data needs no dedicated scope.
    assert s.scopes == "read:tickets read:assets read:customers"
    assert s.page_size == 50
    assert s.timeout == 5.0
    assert s.tenant is None


def test_secret_is_not_exposed_in_repr(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(client_secret="super-secret-value")
    # pydantic SecretStr must mask the value in any string rendering.
    assert "super-secret-value" not in repr(s)
    assert "super-secret-value" not in str(s)
    # but the real value is retrievable via the explicit accessor.
    assert s.client_secret.get_secret_value() == "super-secret-value"


def test_required_fields_raise_when_missing() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]


def test_page_size_is_bounded(make_settings: Callable[..., Settings]) -> None:
    with pytest.raises(ValidationError):
        make_settings(page_size=0)
    # Halo caps list responses at 100 rows/page, so the setting is bounded to match.
    with pytest.raises(ValidationError):
        make_settings(page_size=101)
    assert make_settings(page_size=100).page_size == 100


def test_enable_writes_parses_truthy_strings(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(enable_writes="true").enable_writes is True
    assert make_settings(enable_writes="false").enable_writes is False


def test_portal_url_derived_from_api_url(make_settings: Callable[..., Settings]) -> None:
    # HALO_API_URL is the Resource Server API base (…/api); the web portal used
    # for deep links lives at the same scheme+host with no path. Never
    # hardcoded — this must work for whatever host is in a user's own .env.
    s = make_settings(api_url="https://acme.haloitsm.com/api")
    assert s.portal_url == "https://acme.haloitsm.com"


def test_portal_url_ignores_deeper_api_paths(make_settings: Callable[..., Settings]) -> None:
    s = make_settings(api_url="https://support.example.com/haloapi/api")
    assert s.portal_url == "https://support.example.com"
