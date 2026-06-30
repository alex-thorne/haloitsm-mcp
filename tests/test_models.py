"""Tests for the compact DTO projections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from halo_mcp.models import AgentSummary, ClientSummary, TicketSummary


def test_ticket_summary_trims_to_compact_fields() -> None:
    raw = {
        "id": 42,
        "summary": "Printer down",
        "status_id": 1,
        "client_id": 9,
        "client_name": "Acme",
        "agent_id": 3,
        "team": "1st Line",
        "dateoccurred": "2026-06-29T15:41:46.637",
        # noise the model must drop:
        "details": "x" * 5000,
        "custom_fields": [{"a": 1}],
        "thirdpartyref": "ZZZ",
    }
    assert TicketSummary.project(raw) == {
        "id": 42,
        "summary": "Printer down",
        "status_id": 1,
        "client_id": 9,
        "client_name": "Acme",
        "agent_id": 3,
        "team": "1st Line",
        "dateoccurred": "2026-06-29T15:41:46.637",
    }


def test_project_many_preserves_order() -> None:
    out = TicketSummary.project_many([{"id": 1}, {"id": 2}, {"id": 3}])
    assert [t["id"] for t in out] == [1, 2, 3]


def test_optional_fields_default_to_none() -> None:
    assert ClientSummary.project({"id": 5}) == {"id": 5, "name": None}


def test_missing_required_id_raises() -> None:
    with pytest.raises(ValidationError):
        AgentSummary.project({"name": "no id"})
