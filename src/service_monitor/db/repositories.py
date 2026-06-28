"""Data access helpers for monitors and check results."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AlertEvent,
    AlertSettings,
    CheckResult,
    Monitor,
    StatusPage,
    StatusPageComponent,
    StatusPageComponentMonitor,
)


def count_monitors(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Monitor)) or 0


def list_monitors(session: Session) -> list[Monitor]:
    return list(session.scalars(select(Monitor).order_by(Monitor.id)).all())


def list_active_monitors(session: Session) -> list[Monitor]:
    return list(
        session.scalars(
            select(Monitor).where(Monitor.is_paused.is_(False)).order_by(Monitor.id)
        ).all()
    )


def get_monitor(session: Session, monitor_id: int) -> Monitor | None:
    return session.get(Monitor, monitor_id)


def create_monitor(session: Session, **fields: object) -> Monitor:
    monitor = Monitor(**fields)
    session.add(monitor)
    session.flush()
    session.refresh(monitor)
    return monitor


def update_monitor(session: Session, monitor: Monitor, **fields: object) -> Monitor:
    for key, value in fields.items():
        setattr(monitor, key, value)
    monitor.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(monitor)
    return monitor


def delete_monitor(session: Session, monitor: Monitor) -> None:
    session.delete(monitor)


def create_check_result(session: Session, **fields: object) -> CheckResult:
    result = CheckResult(**fields)
    session.add(result)
    session.flush()
    session.refresh(result)
    return result


def list_check_results(
    session: Session,
    monitor_id: int,
    *,
    limit: int = 50,
) -> list[CheckResult]:
    return list(
        session.scalars(
            select(CheckResult)
            .where(CheckResult.monitor_id == monitor_id)
            .order_by(CheckResult.checked_at.desc(), CheckResult.id.desc())
            .limit(limit)
        ).all()
    )


DEFAULT_STATUS_PAGE_SLUG = "default"
DEFAULT_STATUS_PAGE_TITLE = "Service Status"
DEFAULT_COMPONENT_NAME = "Core services"


def get_status_page_by_slug(session: Session, slug: str) -> StatusPage | None:
    return session.scalar(select(StatusPage).where(StatusPage.slug == slug))


def get_default_status_page(session: Session) -> StatusPage | None:
    return get_status_page_by_slug(session, DEFAULT_STATUS_PAGE_SLUG)


def create_status_page(session: Session, **fields: object) -> StatusPage:
    page = StatusPage(**fields)
    session.add(page)
    session.flush()
    session.refresh(page)
    return page


def update_status_page(session: Session, page: StatusPage, **fields: object) -> StatusPage:
    for key, value in fields.items():
        setattr(page, key, value)
    page.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(page)
    return page


def list_status_page_components(session: Session, status_page_id: int) -> list[StatusPageComponent]:
    return list(
        session.scalars(
            select(StatusPageComponent)
            .where(StatusPageComponent.status_page_id == status_page_id)
            .order_by(StatusPageComponent.sort_order, StatusPageComponent.id)
        ).all()
    )


def get_status_page_component(session: Session, component_id: int) -> StatusPageComponent | None:
    return session.get(StatusPageComponent, component_id)


def create_status_page_component(session: Session, **fields: object) -> StatusPageComponent:
    component = StatusPageComponent(**fields)
    session.add(component)
    session.flush()
    session.refresh(component)
    return component


def update_status_page_component(
    session: Session,
    component: StatusPageComponent,
    **fields: object,
) -> StatusPageComponent:
    for key, value in fields.items():
        setattr(component, key, value)
    session.flush()
    session.refresh(component)
    return component


def delete_status_page_component(session: Session, component: StatusPageComponent) -> None:
    session.delete(component)


def get_component_monitor_link(
    session: Session,
    component_id: int,
    monitor_id: int,
) -> StatusPageComponentMonitor | None:
    return session.scalar(
        select(StatusPageComponentMonitor).where(
            StatusPageComponentMonitor.component_id == component_id,
            StatusPageComponentMonitor.monitor_id == monitor_id,
        )
    )


def add_monitor_to_component(
    session: Session,
    component_id: int,
    monitor_id: int,
) -> StatusPageComponentMonitor:
    link = StatusPageComponentMonitor(component_id=component_id, monitor_id=monitor_id)
    session.add(link)
    session.flush()
    session.refresh(link)
    return link


def remove_monitor_from_component(session: Session, link: StatusPageComponentMonitor) -> None:
    session.delete(link)


def list_component_monitors(session: Session, component_id: int) -> list[Monitor]:
    return list(
        session.scalars(
            select(Monitor)
            .join(StatusPageComponentMonitor, StatusPageComponentMonitor.monitor_id == Monitor.id)
            .where(StatusPageComponentMonitor.component_id == component_id)
            .order_by(Monitor.id)
        ).all()
    )


def get_alert_settings(session: Session) -> AlertSettings | None:
    return session.scalar(select(AlertSettings).order_by(AlertSettings.id).limit(1))


def ensure_alert_settings(session: Session) -> AlertSettings:
    settings = get_alert_settings(session)
    if settings is not None:
        return settings
    settings = AlertSettings()
    session.add(settings)
    session.flush()
    session.refresh(settings)
    return settings


def update_alert_settings(session: Session, settings: AlertSettings, **fields: object) -> AlertSettings:
    for key, value in fields.items():
        setattr(settings, key, value)
    settings.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(settings)
    return settings


def create_alert_event(session: Session, **fields: object) -> AlertEvent:
    event = AlertEvent(**fields)
    session.add(event)
    session.flush()
    session.refresh(event)
    return event


def list_alert_events(session: Session, *, limit: int = 50) -> list[AlertEvent]:
    return list(
        session.scalars(
            select(AlertEvent).order_by(AlertEvent.created_at.desc(), AlertEvent.id.desc()).limit(limit)
        ).all()
    )
