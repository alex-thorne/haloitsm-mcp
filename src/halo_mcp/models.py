"""Compact DTO projections for the Halo entities the tools surface.

Halo responses are large; tools return only these trimmed shapes to keep tool
output small (ids, key fields, status). Each model ignores unknown fields, so a
raw Halo blob can be projected straight through ``Model.project(raw)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

# Halo represents an "unset" date with a 1899/1900 sentinel; treat those as None
# so callers don't mistake them for real response/target dates.
_UNSET_DATE_PREFIXES = ("1899", "1900-01-01")


def _blank_sentinel_dates(data: dict[str, Any], keys: tuple[str, ...]) -> None:
    """In-place: null out Halo's 1899/1900 sentinel dates for the given keys."""
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.startswith(_UNSET_DATE_PREFIXES):
            data[key] = None


class _HaloModel(BaseModel):
    """Base DTO: ignore unknown Halo fields and expose projection helpers."""

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def project(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate a raw Halo record and return only the compact fields."""
        return cls.model_validate(raw).model_dump()

    @classmethod
    def project_many(cls, raws: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [cls.project(raw) for raw in raws]


class TicketSummary(_HaloModel):
    id: int
    summary: str | None = None
    status_id: int | None = None
    tickettype_id: int | None = None
    priority_id: int | None = None
    priority_name: str | None = None  # flattened from the nested Halo priority object
    client_id: int | None = None
    client_name: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    site_id: int | None = None
    site_name: str | None = None
    agent_id: int | None = None
    team: str | None = None
    team_id: int | None = None
    sla_id: int | None = None
    sla_name: str | None = None
    slaresponsestate: str | None = None  # Halo first-response SLA state code
    excludefromsla: bool | None = None
    respondbydate: str | None = None  # first-response SLA deadline
    responsedate: str | None = None  # first actual response
    targetdate: str | None = None  # fix-by / resolution SLA deadline
    fixbydate: str | None = None
    # Halo's logged/created date for the ticket (ISO-8601 string).
    dateoccurred: str | None = None
    datecreated: str | None = None
    last_update: str | None = None
    lastactiondate: str | None = None
    category_1: str | None = None
    onhold: bool | None = None
    # Browser-openable deep link to this ticket on the configured Halo instance.
    # Never present on the raw Halo payload; callers attach it after projection
    # (see tools/read.py, tools/write.py) since it depends on HaloClient.portal_url.
    url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_and_clean(cls, raw: Any) -> Any:
        """Flatten the nested priority name and null Halo's sentinel dates."""
        if not isinstance(raw, dict):
            return raw
        data = dict(raw)
        priority = data.get("priority")
        if isinstance(priority, dict) and data.get("priority_name") is None:
            data["priority_name"] = priority.get("name")
        _blank_sentinel_dates(
            data,
            (
                "respondbydate",
                "responsedate",
                "targetdate",
                "fixbydate",
                "datecreated",
                "last_update",
                "lastactiondate",
                "dateoccurred",
            ),
        )
        return data


class TicketActionSummary(_HaloModel):
    id: int
    ticket_id: int | None = None
    outcome: str | None = None
    outcome_id: int | None = None
    note: str | None = None
    who: str | None = None
    who_type: int | None = None
    datetime: str | None = None
    timetaken: float | None = None
    old_status: int | None = None
    new_status: int | None = None
    new_status_name: str | None = None
    emaildirection: str | None = None  # 'I' inbound / 'O' outbound — support channel signal
    email_status: int | None = None
    important: bool | None = None
    hiddenfromuser: bool | None = None  # private (agent-only) vs client-visible note
    attachment_count: int | None = None


class ClientSummary(_HaloModel):
    id: int
    name: str | None = None


class UserSummary(_HaloModel):
    id: int
    name: str | None = None
    emailaddress: str | None = None
    client_id: int | None = None


class AgentSummary(_HaloModel):
    id: int
    name: str | None = None
    email: str | None = None


class AppointmentSummary(_HaloModel):
    id: int
    subject: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    agent_id: int | None = None


class AssetSummary(_HaloModel):
    id: int
    inventory_number: str | None = None
    client_id: int | None = None
    client_name: str | None = None
    assettype_name: str | None = None


class AttachmentSummary(_HaloModel):
    id: int
    filename: str | None = None
    ticket_id: int | None = None


class TeamSummary(_HaloModel):
    id: int | None = None
    name: str | None = None


class SiteSummary(_HaloModel):
    id: int
    name: str | None = None
    client_id: int | None = None
    client_name: str | None = None


class StatusSummary(_HaloModel):
    id: int
    name: str | None = None


class SupplierSummary(_HaloModel):
    id: int
    name: str | None = None


class TicketTypeSummary(_HaloModel):
    id: int
    name: str | None = None


class ProjectSummary(_HaloModel):
    id: int
    name: str | None = None
    summary: str | None = None
    client_id: int | None = None
    client_name: str | None = None


class InvoiceSummary(_HaloModel):
    id: int
    client_id: int | None = None
    client_name: str | None = None
    invoice_date: str | None = None
    total: float | None = None


class ItemSummary(_HaloModel):
    id: int
    name: str | None = None


class OpportunitySummary(_HaloModel):
    id: int
    name: str | None = None
    client_id: int | None = None
    client_name: str | None = None


class ReportSummary(_HaloModel):
    id: int
    name: str | None = None


class PrioritySummary(_HaloModel):
    priorityid: int | None = None
    name: str | None = None
    responsetime: float | None = None
    responseunits: str | None = None
    fixtime: float | None = None
    fixunits: str | None = None
    slaid: int | None = None
    ishidden: bool | None = None


class SlaSummary(_HaloModel):
    id: int
    name: str | None = None
    workday_id: int | None = None
    trackslaresponsetime: bool | None = None
    trackslafixbytime: bool | None = None


class CategorySummary(_HaloModel):
    id: int
    category_name: str | None = None
    value: str | None = None
    itilrequesttype: int | None = None
    sla_id: int | None = None
    priority_id: int | None = None
    type_id: int | None = None
    category_group_id: int | None = None
