"""Shared monitor status transition evaluation for alerts and incidents."""

from __future__ import annotations

from dataclasses import dataclass

from ..db.models import Monitor, MonitorState
from .state import STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN, STATUS_UP


@dataclass(frozen=True)
class MonitorTransition:
    old_status: str
    new_status: str
    went_down: bool
    recovered: bool


def normalize_monitor_status(status: str | None) -> str:
    if status in {STATUS_UP, STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN}:
        return status
    return STATUS_UNKNOWN


def evaluate_monitor_transition(
    previous_status: str | None,
    monitor_state: MonitorState,
    monitor: Monitor,
) -> MonitorTransition:
    old_status = normalize_monitor_status(previous_status)
    new_status = normalize_monitor_status(monitor_state.last_status)

    went_down = (
        not monitor.is_paused
        and new_status == STATUS_DOWN
        and old_status != STATUS_DOWN
    )
    recovered = (
        not monitor.is_paused
        and new_status == STATUS_UP
        and old_status == STATUS_DOWN
    )

    return MonitorTransition(
        old_status=old_status,
        new_status=new_status,
        went_down=went_down,
        recovered=recovered,
    )
