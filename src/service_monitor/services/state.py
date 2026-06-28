"""Monitor state aggregation and check-result persistence."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..config import Settings
from .checks import CheckOutcome
from ..db.models import CheckResult, Monitor, MonitorState

STATUS_PAUSED = "paused"
STATUS_UP = "up"
STATUS_DOWN = "down"
STATUS_UNKNOWN = "unknown"


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _uptime_ratio(session: Session, monitor_id: int, window: timedelta) -> float | None:
    cutoff = datetime.now(UTC) - window
    total = session.scalar(
        select(func.count())
        .select_from(CheckResult)
        .where(CheckResult.monitor_id == monitor_id, CheckResult.checked_at >= cutoff)
    )
    if not total:
        return None
    successes = session.scalar(
        select(func.count())
        .select_from(CheckResult)
        .where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at >= cutoff,
            CheckResult.success.is_(True),
        )
    )
    return round((successes or 0) / total, 6)


def derive_status(monitor: Monitor, outcome: CheckOutcome | None, *, has_checks: bool) -> str:
    if monitor.is_paused:
        return STATUS_PAUSED
    if not has_checks and outcome is None:
        return STATUS_UNKNOWN
    if outcome is None:
        return STATUS_UNKNOWN
    return STATUS_UP if outcome.success else STATUS_DOWN


def get_or_create_monitor_state(session: Session, monitor_id: int) -> MonitorState:
    state = session.get(MonitorState, monitor_id)
    if state is None:
        state = MonitorState(monitor_id=monitor_id, updated_at=datetime.now(UTC))
        session.add(state)
        session.flush()
    return state


def update_monitor_state_from_outcome(
    session: Session,
    monitor: Monitor,
    outcome: CheckOutcome,
) -> MonitorState:
    state = get_or_create_monitor_state(session, monitor.id)
    previous_failures = state.consecutive_failures

    if monitor.is_paused:
        state.last_status = STATUS_PAUSED
    elif outcome.success:
        state.consecutive_failures = 0
        state.last_status = STATUS_UP
    else:
        state.consecutive_failures = previous_failures + 1
        state.last_status = STATUS_DOWN

    state.last_check_at = _ensure_utc(outcome.checked_at)
    state.last_status_code = outcome.status_code
    state.last_response_time_ms = outcome.response_time_ms
    state.uptime_ratio_24h = _uptime_ratio(session, monitor.id, timedelta(hours=24))
    state.uptime_ratio_7d = _uptime_ratio(session, monitor.id, timedelta(days=7))
    state.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(state)
    return state


def sync_paused_monitor_state(session: Session, monitor: Monitor) -> MonitorState:
    state = get_or_create_monitor_state(session, monitor.id)
    state.last_status = STATUS_PAUSED if monitor.is_paused else state.last_status
    if monitor.is_paused:
        state.consecutive_failures = 0
    state.updated_at = datetime.now(UTC)
    session.flush()
    session.refresh(state)
    return state


def prune_old_check_results(session: Session, monitor_id: int, retention_days: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    result = session.execute(
        delete(CheckResult).where(
            CheckResult.monitor_id == monitor_id,
            CheckResult.checked_at < cutoff,
        )
    )
    return result.rowcount or 0


def record_check_result(
    session: Session,
    monitor: Monitor,
    outcome: CheckOutcome,
    settings: Settings,
) -> CheckResult:
    state = get_or_create_monitor_state(session, monitor.id)
    previous_status = state.last_status

    check_result = CheckResult(
        monitor_id=monitor.id,
        checked_at=_ensure_utc(outcome.checked_at),
        status_code=outcome.status_code,
        response_time_ms=outcome.response_time_ms,
        success=outcome.success,
        error_message=outcome.error_message,
    )
    session.add(check_result)
    session.flush()
    update_monitor_state_from_outcome(session, monitor, outcome)
    prune_old_check_results(session, monitor.id, settings.data_retention_days)

    from .alerts import process_monitor_alert_transition

    process_monitor_alert_transition(
        session,
        monitor,
        state,
        outcome,
        check_result,
        settings,
        previous_status=previous_status,
    )
    return check_result
