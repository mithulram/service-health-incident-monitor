"""In-memory public sample payloads when no real monitoring data exists yet."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..db import repositories as repo
from ..db.models import StatusPage

SAMPLE_REASON = "No monitors have been configured yet"

SAMPLE_INCIDENTS: tuple[dict[str, Any], ...] = (
    {
        "identifier": "SAMPLE-001",
        "service": "Example API",
        "severity": "SEV-3",
        "status": "RESOLVED",
        "summary": (
            "Sample resolved incident for dashboard preview. "
            "Configure monitors to track real outages."
        ),
        "started_at": "2026-06-18T15:26:00Z",
        "is_sample": True,
    },
    {
        "identifier": "SAMPLE-002",
        "service": "Background jobs",
        "severity": "SEV-3",
        "status": "OPEN",
        "summary": (
            "Sample open incident for dashboard preview. "
            "This is not real monitoring data."
        ),
        "started_at": "2026-06-19T08:14:00Z",
        "is_sample": True,
    },
)


def should_use_public_sample_data(session: Session) -> bool:
    """True when the database has no configured monitors or incidents."""
    return repo.count_monitors(session) == 0 and repo.count_incidents(session) == 0


def sample_summary_payload(state_summary: dict[str, float | int]) -> dict[str, float | int | bool | str | None]:
    """Return a dashboard summary preview without persisting rows."""
    open_count = sum(1 for item in SAMPLE_INCIDENTS if item["status"] == "OPEN")
    return {
        **state_summary,
        "monitors_total": 3,
        "monitors_up": 2,
        "monitors_down": 0,
        "monitors_paused": 1,
        "monitors_unknown": 0,
        "average_response_time_ms_24h": 142.5,
        "open_incident_count": open_count,
        "is_sample_data": True,
        "sample_reason": SAMPLE_REASON,
    }


def sample_incidents_payload() -> list[dict[str, object]]:
    return [dict(item) for item in SAMPLE_INCIDENTS]


def sample_public_status_payload(page: StatusPage) -> dict[str, object]:
    """Return a public status preview without monitor URLs or DB rows."""
    updated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {
        "title": page.title,
        "slug": page.slug,
        "overall_status": "operational",
        "updated_at": updated_at,
        "is_sample_data": True,
        "sample_reason": SAMPLE_REASON,
        "components": [
            {
                "id": -1,
                "name": "Core services (sample preview)",
                "status": "operational",
                "is_sample": True,
                "monitors": [
                    {
                        "id": -1,
                        "name": "Example API",
                        "status": "up",
                        "last_check_at": None,
                        "last_response_time_ms": 118,
                        "is_sample": True,
                    },
                    {
                        "id": -2,
                        "name": "Background jobs",
                        "status": "up",
                        "last_check_at": None,
                        "last_response_time_ms": 164,
                        "is_sample": True,
                    },
                ],
            },
            {
                "id": -2,
                "name": "Notifications (sample preview)",
                "status": "operational",
                "is_sample": True,
                "monitors": [
                    {
                        "id": -3,
                        "name": "Email delivery",
                        "status": "paused",
                        "last_check_at": None,
                        "last_response_time_ms": None,
                        "is_sample": True,
                    },
                ],
            },
        ],
        "recent_incidents": [],
    }
