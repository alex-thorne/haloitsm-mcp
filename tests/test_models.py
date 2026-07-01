"""Tests for the compact DTO projections."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from halo_mcp.models import (
    AgentSummary,
    CategorySummary,
    ClientSummary,
    PrioritySummary,
    SlaSummary,
    TicketActionSummary,
    TicketSummary,
)


def test_ticket_summary_trims_to_compact_fields() -> None:
    raw = {
        "id": 42,
        "summary": "Printer down",
        "status_id": 2,
        "tickettype_id": 55,
        "priority_id": 3,
        "priority": {"priorityid": 3, "name": "P3 Medium", "responsetime": 4.0},
        "client_id": 9,
        "client_name": "Acme",
        "user_id": 7,
        "user_name": "sam",
        "site_id": 21,
        "site_name": "HQ",
        "agent_id": 3,
        "team": "1st Line",
        "team_id": 13,
        "sla_id": 8,
        "sla_name": "Std SLA",
        "slaresponsestate": "I",
        "respondbydate": "2026-07-01T09:00:00",
        "responsedate": "2026-06-30T16:04:27.21",
        "targetdate": "1900-01-01T00:00:00",
        "fixbydate": "1899-12-30T00:00:00",
        "dateoccurred": "2026-06-29T15:41:46.637",
        "datecreated": "2026-06-29T15:41:46.637",
        "last_update": "2026-06-30T16:04:28.36",
        "lastactiondate": "2026-06-30T16:04:27.857",
        "category_1": "",
        "onhold": False,
        # noise the model must drop:
        "details": "x" * 5000,
        "custom_fields": [{"a": 1}],
        "thirdpartyref": "ZZZ",
    }
    assert TicketSummary.project(raw) == {
        "id": 42,
        "summary": "Printer down",
        "status_id": 2,
        "tickettype_id": 55,
        "priority_id": 3,
        "priority_name": "P3 Medium",
        "client_id": 9,
        "client_name": "Acme",
        "user_id": 7,
        "user_name": "sam",
        "site_id": 21,
        "site_name": "HQ",
        "agent_id": 3,
        "team": "1st Line",
        "team_id": 13,
        "sla_id": 8,
        "sla_name": "Std SLA",
        "slaresponsestate": "I",
        "respondbydate": "2026-07-01T09:00:00",
        "responsedate": "2026-06-30T16:04:27.21",
        "excludefromsla": None,
        # Halo's 1899/1900 sentinel "unset" dates are nulled.
        "targetdate": None,
        "fixbydate": None,
        "dateoccurred": "2026-06-29T15:41:46.637",
        "datecreated": "2026-06-29T15:41:46.637",
        "last_update": "2026-06-30T16:04:28.36",
        "lastactiondate": "2026-06-30T16:04:27.857",
        "category_1": "",
        "onhold": False,
        # Not present on the raw Halo payload; attached later by tools/read.py
        # and tools/write.py once the ticket id is known.
        "url": None,
    }
    out = TicketSummary.project({"id": 1, "priority_id": 3})
    assert out["priority_id"] == 3
    assert out["priority_name"] is None


def test_ticket_action_summary_expands_workflow_and_channel_fields() -> None:
    raw = {
        "id": 1,
        "ticket_id": 55,
        "outcome": "Email Received",
        "outcome_id": 12,
        "note": "customer replied",
        "who": "Sam",
        "who_type": 0,
        "datetime": "2026-06-30T16:04:27.857",
        "timetaken": 0.05,
        "old_status": 1,
        "new_status": 2,
        "new_status_name": "In Progress",
        "emaildirection": "I",
        "email_status": 2,
        "important": False,
        "hiddenfromuser": True,
        "attachment_count": 0,
        # noise:
        "guid": "abc",
        "translations": [1, 2],
        "emailfrom": "a@b",
    }
    out = TicketActionSummary.project(raw)
    assert out["emaildirection"] == "I"
    assert out["new_status_name"] == "In Progress" and out["old_status"] == 1
    assert out["timetaken"] == 0.05 and out["hiddenfromuser"] is True
    assert "guid" not in out and "emailfrom" not in out


def test_priority_summary_projection() -> None:
    assert PrioritySummary.project(
        {
            "priorityid": 4,
            "name": "P4-Low",
            "responsetime": 8.0,
            "responseunits": "H",
            "fixtime": 9999.0,
            "fixunits": "D",
            "slaid": 8,
            "ishidden": False,
            "colour": "#fff",
            "junk": 1,
        }
    ) == {
        "priorityid": 4,
        "name": "P4-Low",
        "responsetime": 8.0,
        "responseunits": "H",
        "fixtime": 9999.0,
        "fixunits": "D",
        "slaid": 8,
        "ishidden": False,
    }


def test_sla_summary_projection() -> None:
    assert SlaSummary.project(
        {
            "id": 1,
            "name": "Std",
            "workday_id": 1,
            "trackslaresponsetime": True,
            "trackslafixbytime": False,
            "junk": 1,
        }
    ) == {
        "id": 1,
        "name": "Std",
        "workday_id": 1,
        "trackslaresponsetime": True,
        "trackslafixbytime": False,
    }


def test_category_summary_projection() -> None:
    assert CategorySummary.project(
        {
            "id": 16,
            "category_name": "Account Administration",
            "value": "Account Administration",
            "itilrequesttype": 0,
            "sla_id": -1,
            "priority_id": -1,
            "type_id": 1,
            "category_group_id": 0,
            "junk": 1,
        }
    ) == {
        "id": 16,
        "category_name": "Account Administration",
        "value": "Account Administration",
        "itilrequesttype": 0,
        "sla_id": -1,
        "priority_id": -1,
        "type_id": 1,
        "category_group_id": 0,
    }


def test_project_many_preserves_order() -> None:
    out = TicketSummary.project_many([{"id": 1}, {"id": 2}, {"id": 3}])
    assert [t["id"] for t in out] == [1, 2, 3]


def test_optional_fields_default_to_none() -> None:
    assert ClientSummary.project({"id": 5}) == {"id": 5, "name": None}


def test_missing_required_id_raises() -> None:
    with pytest.raises(ValidationError):
        AgentSummary.project({"name": "no id"})
