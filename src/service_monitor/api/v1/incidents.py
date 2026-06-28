"""Incident list, detail, and timeline routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import require_admin
from ...db.engine import get_session
from ...db import repositories as repo
from ...services.incidents import (
    add_manual_incident_update,
    apply_incident_status_change,
    incident_to_api_dict,
    incident_update_to_api_dict,
)

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])


class IncidentUpdateRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class IncidentPatchRequest(BaseModel):
    status: str = Field(min_length=1, max_length=16)


def _parse_incident_status(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"open", "acknowledged", "resolved"}:
        return normalized
    mapping = {
        "OPEN": "open",
        "ACKNOWLEDGED": "acknowledged",
        "RESOLVED": "resolved",
    }
    mapped = mapping.get(value.strip().upper())
    if mapped is not None:
        return mapped
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported incident status.")


class IncidentUpdateResponse(BaseModel):
    id: int
    incident_id: int
    message: str
    status: str | None
    created_at: datetime


@router.get("/{incident_id}")
def get_incident_route(
    incident_id: int,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    incident = repo.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")
    return incident_to_api_dict(incident)


@router.patch("/{incident_id}", dependencies=[Depends(require_admin)])
def update_incident_route(
    incident_id: int,
    payload: IncidentPatchRequest,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    incident = repo.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    normalized = _parse_incident_status(payload.status)
    try:
        incident = apply_incident_status_change(session, incident, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    incident = repo.get_incident(session, incident.id)
    assert incident is not None
    return incident_to_api_dict(incident)


@router.get("/{incident_id}/updates", response_model=list[IncidentUpdateResponse])
def list_incident_updates_route(
    incident_id: int,
    session: Session = Depends(get_session),
) -> list[IncidentUpdateResponse]:
    incident = repo.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    updates = repo.list_incident_updates(session, incident_id)
    return [
        IncidentUpdateResponse(**incident_update_to_api_dict(update))
        for update in updates
    ]


@router.post(
    "/{incident_id}/updates",
    response_model=IncidentUpdateResponse,
    dependencies=[Depends(require_admin)],
)
def add_incident_update_route(
    incident_id: int,
    payload: IncidentUpdateRequest,
    session: Session = Depends(get_session),
) -> IncidentUpdateResponse:
    incident = repo.get_incident(session, incident_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incident not found.")

    update = add_manual_incident_update(session, incident, payload.message)
    return IncidentUpdateResponse(**incident_update_to_api_dict(update))
