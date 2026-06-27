"""Data access helpers for monitors and check results."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import CheckResult, Monitor


def count_monitors(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Monitor)) or 0


def list_monitors(session: Session) -> list[Monitor]:
    return list(session.scalars(select(Monitor).order_by(Monitor.id)).all())


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
