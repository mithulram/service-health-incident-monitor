"""Fleet-level monitor statistics for summary endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db.models import CheckResult, Monitor, MonitorState
from .state import STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN, STATUS_UP


def fleet_summary(session: Session) -> dict[str, int | float | None]:
    monitors = list(session.scalars(select(Monitor)).all())
    states = {
        state.monitor_id: state
        for state in session.scalars(select(MonitorState)).all()
    }

    counts = {
        "monitors_total": len(monitors),
        "monitors_up": 0,
        "monitors_down": 0,
        "monitors_paused": 0,
        "monitors_unknown": 0,
    }

    for monitor in monitors:
        state = states.get(monitor.id)
        status = state.last_status if state and state.last_status else STATUS_UNKNOWN
        if monitor.is_paused or status == STATUS_PAUSED:
            counts["monitors_paused"] += 1
        elif status == STATUS_UP:
            counts["monitors_up"] += 1
        elif status == STATUS_DOWN:
            counts["monitors_down"] += 1
        else:
            counts["monitors_unknown"] += 1

    cutoff = datetime.now(UTC) - timedelta(hours=24)
    average_response_time_ms_24h = session.scalar(
        select(func.avg(CheckResult.response_time_ms)).where(
            CheckResult.checked_at >= cutoff,
            CheckResult.response_time_ms.is_not(None),
        )
    )

    return {
        **counts,
        "average_response_time_ms_24h": (
            round(float(average_response_time_ms_24h), 2)
            if average_response_time_ms_24h is not None
            else None
        ),
    }
