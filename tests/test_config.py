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
    # Default scopes are the least-privilege read set.
    assert s.scopes == "read:tickets read:assets read:customers read:users read:agents"
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
    with pytest.raises(ValidationError):
        make_settings(page_size=1001)
    assert make_settings(page_size=1000).page_size == 1000


def test_enable_writes_parses_truthy_strings(make_settings: Callable[..., Settings]) -> None:
    assert make_settings(enable_writes="true").enable_writes is True
    assert make_settings(enable_writes="false").enable_writes is False
