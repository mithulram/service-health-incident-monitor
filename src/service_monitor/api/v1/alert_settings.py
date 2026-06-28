"""Admin alert settings routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import get_app_settings, require_admin
from ...config import Settings
from ...db.engine import get_session
from ...db import repositories as repo
from ...services.alerts import (
    build_alert_settings_response,
    ensure_default_alert_settings,
    send_test_alert,
)

router = APIRouter(prefix="/api/v1/settings/alerts", tags=["alert-settings"])


class AlertSettingsUpdate(BaseModel):
    enabled: bool | None = None
    send_resolved: bool | None = None
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = Field(default=None, max_length=255)
    smtp_from: str | None = Field(default=None, max_length=255)
    alert_to: str | None = Field(default=None, max_length=255)


class AlertEventResponse(BaseModel):
    id: int
    monitor_id: int | None
    check_result_id: int | None
    event_type: str
    recipient: str
    subject: str
    success: bool
    error_message: str | None
    created_at: datetime


@router.get("", dependencies=[Depends(require_admin)])
def get_alert_settings_route(
    request_settings: Settings = Depends(get_app_settings),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    alert_settings = ensure_default_alert_settings(session)
    return build_alert_settings_response(request_settings, alert_settings)


@router.patch("", dependencies=[Depends(require_admin)])
def update_alert_settings_route(
    payload: AlertSettingsUpdate,
    request_settings: Settings = Depends(get_app_settings),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    alert_settings = ensure_default_alert_settings(session)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        if "smtp_from" in updates and updates["smtp_from"] is not None:
            updates["smtp_from"] = str(updates["smtp_from"])
        if "alert_to" in updates and updates["alert_to"] is not None:
            updates["alert_to"] = str(updates["alert_to"])
        alert_settings = repo.update_alert_settings(session, alert_settings, **updates)
    return build_alert_settings_response(request_settings, alert_settings)


@router.post("/test", dependencies=[Depends(require_admin)])
def send_test_alert_route(
    request_settings: Settings = Depends(get_app_settings),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    alert_settings = ensure_default_alert_settings(session)
    try:
        event = send_test_alert(session, request_settings, alert_settings)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not event.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=event.error_message or "Test alert email failed to send.",
        )

    return {
        "status": "sent",
        "event_id": event.id,
        "recipient": event.recipient,
    }


@router.get("/events", response_model=list[AlertEventResponse], dependencies=[Depends(require_admin)])
def list_alert_events_route(
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[AlertEventResponse]:
    events = repo.list_alert_events(session, limit=limit)
    return [
        AlertEventResponse(
            id=event.id,
            monitor_id=event.monitor_id,
            check_result_id=event.check_result_id,
            event_type=event.event_type,
            recipient=event.recipient,
            subject=event.subject,
            success=event.success,
            error_message=event.error_message,
            created_at=event.created_at,
        )
        for event in events
    ]
