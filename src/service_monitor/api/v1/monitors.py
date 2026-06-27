"""Monitor CRUD schemas and API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, HttpUrl, field_validator
from sqlalchemy.orm import Session

from ...auth import get_app_settings, require_admin
from ...config import Settings
from ...db.engine import get_session
from ...db import repositories as repo
from ...db.models import Monitor
from ...scheduler import MonitorScheduler
from ...services.check_runner import execute_monitor_check
from ...services.state import get_or_create_monitor_state, sync_paused_monitor_state
from ...ssrf import SSRFError, validate_monitor_url

router = APIRouter(prefix="/api/v1", tags=["monitors"])

HttpMethod = Literal["GET", "HEAD"]


class MonitorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    url: HttpUrl
    method: HttpMethod = "GET"
    interval_seconds: int = Field(default=60, ge=30, le=86400)
    timeout_seconds: int = Field(default=5, ge=1, le=30)
    expected_status_min: int = Field(default=200, ge=100, le=599)
    expected_status_max: int = Field(default=399, ge=100, le=599)
    is_paused: bool = False

    @field_validator("expected_status_max")
    @classmethod
    def validate_status_range(cls, expected_status_max: int, info) -> int:
        minimum = info.data.get("expected_status_min", 200)
        if expected_status_max < minimum:
            raise ValueError("expected_status_max must be >= expected_status_min")
        return expected_status_max

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme not in {"http", "https"}:
            raise ValueError("URL must use http or https")
        return value


class MonitorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    url: HttpUrl | None = None
    method: HttpMethod | None = None
    interval_seconds: int | None = Field(default=None, ge=30, le=86400)
    timeout_seconds: int | None = Field(default=None, ge=1, le=30)
    expected_status_min: int | None = Field(default=None, ge=100, le=599)
    expected_status_max: int | None = Field(default=None, ge=100, le=599)
    is_paused: bool | None = None

    @field_validator("url")
    @classmethod
    def validate_url_scheme(cls, value: HttpUrl | None) -> HttpUrl | None:
        if value is not None and value.scheme not in {"http", "https"}:
            raise ValueError("URL must use http or https")
        return value


class MonitorResponse(BaseModel):
    id: int
    name: str
    url: str
    method: str
    interval_seconds: int
    timeout_seconds: int
    expected_status_min: int
    expected_status_max: int
    is_paused: bool
    created_at: datetime
    updated_at: datetime
    last_check_at: datetime | None = None
    last_status: str = "unknown"
    last_status_code: int | None = None
    last_response_time_ms: int | None = None
    consecutive_failures: int = 0
    uptime_ratio_24h: float | None = None
    uptime_ratio_7d: float | None = None


class CheckHistoryItem(BaseModel):
    checked_at: datetime
    status_code: int | None
    response_time_ms: int | None
    success: bool
    error_message: str | None


class CheckRunResponse(BaseModel):
    monitor_id: int
    checked_at: datetime
    status_code: int | None
    response_time_ms: int | None
    success: bool
    error_message: str | None


def get_monitor_scheduler(request: Request) -> MonitorScheduler | None:
    return getattr(request.app.state, "monitor_scheduler", None)


def _monitor_to_response(monitor: Monitor) -> MonitorResponse:
    state = monitor.monitor_state
    return MonitorResponse(
        id=monitor.id,
        name=monitor.name,
        url=monitor.url,
        method=monitor.method,
        interval_seconds=monitor.interval_seconds,
        timeout_seconds=monitor.timeout_seconds,
        expected_status_min=monitor.expected_status_min,
        expected_status_max=monitor.expected_status_max,
        is_paused=monitor.is_paused,
        created_at=monitor.created_at,
        updated_at=monitor.updated_at,
        last_check_at=state.last_check_at if state else None,
        last_status=state.last_status if state and state.last_status else "unknown",
        last_status_code=state.last_status_code if state else None,
        last_response_time_ms=state.last_response_time_ms if state else None,
        consecutive_failures=state.consecutive_failures if state else 0,
        uptime_ratio_24h=state.uptime_ratio_24h if state else None,
        uptime_ratio_7d=state.uptime_ratio_7d if state else None,
    )


def _validate_ssrf_url(url: str) -> None:
    try:
        validate_monitor_url(url)
    except SSRFError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _initialize_monitor_state(session: Session, monitor: Monitor) -> None:
    if monitor.is_paused:
        sync_paused_monitor_state(session, monitor)
    else:
        get_or_create_monitor_state(session, monitor.id)


@router.get("/monitors", response_model=list[MonitorResponse])
def list_monitors(
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> list[MonitorResponse]:
    monitors = repo.list_monitors(session)
    return [_monitor_to_response(monitor) for monitor in monitors]


@router.post("/monitors", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
def create_monitor(
    payload: MonitorCreate,
    request: Request,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> MonitorResponse:
    if repo.count_monitors(session) >= settings.max_monitors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum monitor limit reached ({settings.max_monitors}).",
        )

    url = str(payload.url)
    _validate_ssrf_url(url)

    monitor = repo.create_monitor(
        session,
        name=payload.name.strip(),
        url=url,
        method=payload.method,
        interval_seconds=payload.interval_seconds,
        timeout_seconds=payload.timeout_seconds,
        expected_status_min=payload.expected_status_min,
        expected_status_max=payload.expected_status_max,
        is_paused=payload.is_paused,
    )
    _initialize_monitor_state(session, monitor)
    scheduler = get_monitor_scheduler(request)
    if scheduler is not None:
        scheduler.sync_monitor(monitor)
    session.refresh(monitor)
    return _monitor_to_response(monitor)


@router.get("/monitors/{monitor_id}", response_model=MonitorResponse)
def get_monitor(
    monitor_id: int,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> MonitorResponse:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")
    return _monitor_to_response(monitor)


@router.get("/monitors/{monitor_id}/checks", response_model=list[CheckHistoryItem])
def list_monitor_checks(
    monitor_id: int,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> list[CheckHistoryItem]:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")

    checks = repo.list_check_results(session, monitor_id, limit=limit)
    return [
        CheckHistoryItem(
            checked_at=check.checked_at,
            status_code=check.status_code,
            response_time_ms=check.response_time_ms,
            success=check.success,
            error_message=check.error_message,
        )
        for check in checks
    ]


@router.patch("/monitors/{monitor_id}", response_model=MonitorResponse)
def update_monitor(
    monitor_id: int,
    payload: MonitorUpdate,
    request: Request,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> MonitorResponse:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")

    updates = payload.model_dump(exclude_unset=True)
    if "url" in updates and updates["url"] is not None:
        updates["url"] = str(updates["url"])
        _validate_ssrf_url(updates["url"])

    expected_min = updates.get("expected_status_min", monitor.expected_status_min)
    expected_max = updates.get("expected_status_max", monitor.expected_status_max)
    if expected_max < expected_min:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expected_status_max must be >= expected_status_min",
        )

    if "name" in updates and updates["name"] is not None:
        updates["name"] = updates["name"].strip()

    updated = repo.update_monitor(session, monitor, **updates)
    if "is_paused" in updates:
        sync_paused_monitor_state(session, updated)
    scheduler = get_monitor_scheduler(request)
    if scheduler is not None:
        scheduler.sync_monitor(updated)
    session.refresh(updated)
    return _monitor_to_response(updated)


@router.delete("/monitors/{monitor_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_monitor(
    monitor_id: int,
    request: Request,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
) -> None:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")
    scheduler = get_monitor_scheduler(request)
    if scheduler is not None:
        scheduler.remove_monitor(monitor_id)
    repo.delete_monitor(session, monitor)


@router.post("/checks/run/{monitor_id}", response_model=CheckRunResponse)
def run_check(
    monitor_id: int,
    request: Request,
    _: Annotated[None, Depends(require_admin)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> CheckRunResponse:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.")

    try:
        outcome = execute_monitor_check(session, monitor_id, settings)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found.") from exc

    session.refresh(monitor)
    scheduler = get_monitor_scheduler(request)
    if scheduler is not None:
        scheduler.sync_monitor(monitor)

    return CheckRunResponse(
        monitor_id=monitor.id,
        checked_at=outcome.checked_at,
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        success=outcome.success,
        error_message=outcome.error_message,
    )
