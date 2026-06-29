"""Compact DTO projections for the Halo entities the tools surface.

Halo responses are large; tools return only these trimmed shapes to keep tool
output small (ids, key fields, status). Each model ignores unknown fields, so a
raw Halo blob can be projected straight through ``Model.project(raw)``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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
    client_id: int | None = None
    client_name: str | None = None
    agent_id: int | None = None
    team: str | None = None


class TicketActionSummary(_HaloModel):
    id: int
    ticket_id: int | None = None
    outcome: str | None = None
    note: str | None = None
    who: str | None = None
    datetime: str | None = None


class AssetSummary(_HaloModel):
    id: int
    inventory_number: str | None = None
    client_id: int | None = None
    client_name: str | None = None
    assettype_name: str | None = None


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


class TeamSummary(_HaloModel):
    id: int | None = None
    name: str | None = None


class StatusSummary(_HaloModel):
    id: int
    name: str | None = None
