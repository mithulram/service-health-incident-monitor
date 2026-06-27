"""Unified monitor check execution for manual and scheduled runs."""

from __future__ import annotations

import threading

import httpx
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import repositories as repo
from ..services.checks import CheckOutcome, run_monitor_check
from ..services.state import STATUS_PAUSED, record_check_result, sync_paused_monitor_state

_check_semaphore: threading.Semaphore | None = None
_check_semaphore_limit: int | None = None


def _get_check_semaphore(settings: Settings) -> threading.Semaphore:
    global _check_semaphore, _check_semaphore_limit
    if _check_semaphore is None or _check_semaphore_limit != settings.max_concurrent_checks:
        _check_semaphore = threading.Semaphore(settings.max_concurrent_checks)
        _check_semaphore_limit = settings.max_concurrent_checks
    return _check_semaphore


def reset_check_semaphore_for_tests() -> None:
    global _check_semaphore, _check_semaphore_limit
    _check_semaphore = None
    _check_semaphore_limit = None


def execute_monitor_check(
    session: Session,
    monitor_id: int,
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> CheckOutcome:
    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise LookupError(f"Monitor {monitor_id} not found")

    if monitor.is_paused:
        sync_paused_monitor_state(session, monitor)
        return CheckOutcome(
            checked_at=monitor.updated_at,
            status_code=None,
            response_time_ms=None,
            success=False,
            error_message="Monitor is paused.",
        )

    semaphore = _get_check_semaphore(settings)
    with semaphore:
        outcome = run_monitor_check(monitor, client=client)
        record_check_result(session, monitor, outcome, settings)
    return outcome
