"""Automatic incident creation and lifecycle from monitor checks."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..db import repositories as repo
from ..db.models import CheckResult, Incident, IncidentUpdate, Monitor, MonitorState
from .checks import CheckOutcome
from .monitor_transitions import MonitorTransition


INCIDENT_STATUS_OPEN = "open"
INCIDENT_STATUS_ACKNOWLEDGED = "acknowledged"
INCIDENT_STATUS_RESOLVED = "resolved"

SEVERITY_MINOR = "minor"
SEVERITY_MAJOR = "major"
SEVERITY_CRITICAL = "critical"

SEVERITY_TO_API = {
    SEVERITY_CRITICAL: "SEV-1",
    SEVERITY_MAJOR: "SEV-2",
    SEVERITY_MINOR: "SEV-3",
}

STATUS_TO_API = {
    INCIDENT_STATUS_OPEN: "OPEN",
    INCIDENT_STATUS_ACKNOWLEDGED: "ACKNOWLEDGED",
    INCIDENT_STATUS_RESOLVED: "RESOLVED",
}


def incident_identifier(incident_id: int) -> str:
    return f"INC-{incident_id:04d}"


def severity_to_api(severity: str) -> str:
    return SEVERITY_TO_API.get(severity, "SEV-2")


def status_to_api(status: str) -> str:
    return STATUS_TO_API.get(status, status.upper())


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _format_failure_message(outcome: CheckOutcome) -> str:
    parts: list[str] = []
    if outcome.status_code is not None:
        parts.append(f"HTTP {outcome.status_code}")
    if outcome.error_message:
        parts.append(outcome.error_message)
    if parts:
        return "Monitor check failed: " + "; ".join(parts)
    return "Monitor check failed."


def _format_recovery_message(outcome: CheckOutcome) -> str:
    if outcome.status_code is not None:
        return f"Monitor recovered. Latest check returned HTTP {outcome.status_code}."
    return "Monitor recovered and checks are passing again."


def _incident_summary(incident: Incident) -> str:
    if incident.updates:
        return incident.updates[-1].message
    return incident.title


def incident_to_api_dict(incident: Incident) -> dict[str, object]:
    monitor_name = incident.monitor.name if incident.monitor is not None else None
    service = monitor_name or incident.title.replace(" is down", "")
    return {
        "id": incident.id,
        "identifier": incident_identifier(incident.id),
        "monitor_id": incident.monitor_id,
        "monitor_name": monitor_name,
        "service": service,
        "title": incident.title,
        "severity": severity_to_api(incident.severity),
        "status": status_to_api(incident.status),
        "summary": _incident_summary(incident),
        "started_at": incident.started_at,
        "acknowledged_at": incident.acknowledged_at,
        "resolved_at": incident.resolved_at,
        "auto_created": incident.auto_created,
        "created_at": incident.created_at,
        "updated_at": incident.updated_at,
    }


def incident_update_to_api_dict(update: IncidentUpdate) -> dict[str, object]:
    return {
        "id": update.id,
        "incident_id": update.incident_id,
        "message": update.message,
        "status": status_to_api(update.status) if update.status else None,
        "created_at": update.created_at,
    }


def incident_to_public_dict(incident: Incident) -> dict[str, object]:
    return {
        "title": incident.title,
        "status": status_to_api(incident.status),
        "severity": severity_to_api(incident.severity),
        "started_at": incident.started_at,
        "resolved_at": incident.resolved_at,
        "updates_count": len(incident.updates),
    }


def list_incidents_for_api(session: Session) -> list[dict[str, object]]:
    incidents = repo.list_incidents(session)
    return [incident_to_api_dict(incident) for incident in incidents]


def get_open_incident_count(session: Session) -> int | None:
    if repo.count_incidents(session) == 0:
        return None
    return repo.count_open_incidents(session)


def list_recent_public_incidents(session: Session, *, limit: int = 5) -> list[dict[str, object]]:
    incidents = repo.list_recent_incidents(session, limit=limit)
    return [incident_to_public_dict(incident) for incident in incidents]


def process_monitor_incident_transition(
    session: Session,
    monitor: Monitor,
    monitor_state: MonitorState,
    outcome: CheckOutcome,
    check_result: CheckResult,
    transition: MonitorTransition,
) -> None:
    del check_result  # reserved for future correlation

    if transition.went_down and monitor_state.open_incident_id is None:
        started_at = _ensure_utc(outcome.checked_at)
        incident = repo.create_incident(
            session,
            monitor_id=monitor.id,
            title=f"{monitor.name} is down",
            status=INCIDENT_STATUS_OPEN,
            severity=SEVERITY_MAJOR,
            started_at=started_at,
            auto_created=True,
        )
        repo.create_incident_update(
            session,
            incident_id=incident.id,
            message=_format_failure_message(outcome),
            status=INCIDENT_STATUS_OPEN,
        )
        monitor_state.open_incident_id = incident.id
        session.flush()
        return

    if (
        transition.new_status == "down"
        and monitor_state.open_incident_id is not None
        and not transition.went_down
    ):
        incident = repo.get_incident(session, monitor_state.open_incident_id)
        if incident is not None and incident.status in repo.INCIDENT_OPEN_STATUSES:
            updates = repo.list_incident_updates(session, incident.id)
            latest_message = updates[-1].message if updates else ""
            next_message = _format_failure_message(outcome)
            if next_message != latest_message:
                repo.create_incident_update(
                    session,
                    incident_id=incident.id,
                    message=next_message,
                )
                incident.updated_at = datetime.now(UTC)
                session.flush()
        return

    if transition.recovered and monitor_state.open_incident_id is not None:
        incident = repo.get_incident(session, monitor_state.open_incident_id)
        if incident is not None and incident.status in repo.INCIDENT_OPEN_STATUSES:
            resolved_at = _ensure_utc(outcome.checked_at)
            repo.update_incident(
                session,
                incident,
                status=INCIDENT_STATUS_RESOLVED,
                resolved_at=resolved_at,
            )
            repo.create_incident_update(
                session,
                incident_id=incident.id,
                message=_format_recovery_message(outcome),
                status=INCIDENT_STATUS_RESOLVED,
            )
        monitor_state.open_incident_id = None
        session.flush()


def acknowledge_incident(session: Session, incident: Incident) -> Incident:
    if incident.status == INCIDENT_STATUS_RESOLVED:
        raise ValueError("Resolved incidents cannot be acknowledged.")
    acknowledged_at = datetime.now(UTC)
    incident = repo.update_incident(
        session,
        incident,
        status=INCIDENT_STATUS_ACKNOWLEDGED,
        acknowledged_at=acknowledged_at,
    )
    repo.create_incident_update(
        session,
        incident_id=incident.id,
        message="Incident acknowledged.",
        status=INCIDENT_STATUS_ACKNOWLEDGED,
    )
    return incident


def resolve_incident(session: Session, incident: Incident) -> Incident:
    if incident.status == INCIDENT_STATUS_RESOLVED:
        return incident
    resolved_at = datetime.now(UTC)
    incident = repo.update_incident(
        session,
        incident,
        status=INCIDENT_STATUS_RESOLVED,
        resolved_at=resolved_at,
    )
    repo.create_incident_update(
        session,
        incident_id=incident.id,
        message="Incident resolved manually.",
        status=INCIDENT_STATUS_RESOLVED,
    )
    if incident.monitor_id is not None:
        state = session.get(MonitorState, incident.monitor_id)
        if state is not None and state.open_incident_id == incident.id:
            state.open_incident_id = None
            session.flush()
    return incident


def reopen_incident(session: Session, incident: Incident) -> Incident:
    incident = repo.update_incident(
        session,
        incident,
        status=INCIDENT_STATUS_OPEN,
        acknowledged_at=None,
        resolved_at=None,
    )
    repo.create_incident_update(
        session,
        incident_id=incident.id,
        message="Incident reopened.",
        status=INCIDENT_STATUS_OPEN,
    )
    return incident


def apply_incident_status_change(session: Session, incident: Incident, status: str) -> Incident:
    normalized = status.lower()
    if normalized == INCIDENT_STATUS_ACKNOWLEDGED:
        return acknowledge_incident(session, incident)
    if normalized == INCIDENT_STATUS_RESOLVED:
        return resolve_incident(session, incident)
    if normalized == INCIDENT_STATUS_OPEN:
        return reopen_incident(session, incident)
    raise ValueError(f"Unsupported incident status: {status}")


def add_manual_incident_update(session: Session, incident: Incident, message: str) -> IncidentUpdate:
    return repo.create_incident_update(
        session,
        incident_id=incident.id,
        message=message.strip(),
    )
