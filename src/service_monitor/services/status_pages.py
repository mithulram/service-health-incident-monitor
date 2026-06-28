"""Status page aggregation and default page bootstrap."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.orm import Session

from ..db import repositories as repo
from ..db.models import Monitor, StatusPage, StatusPageComponent
from .state import STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN, STATUS_UP

PublicStatus = Literal["operational", "degraded", "outage", "unknown"]
MonitorPublicStatus = Literal["up", "down", "unknown", "paused"]

STATUS_SEVERITY: dict[PublicStatus, int] = {
    "operational": 0,
    "degraded": 1,
    "unknown": 2,
    "outage": 3,
}


def ensure_default_status_page(session: Session) -> StatusPage:
    """Create the default status page idempotently."""
    page = repo.get_default_status_page(session)
    if page is not None:
        return page

    page = repo.create_status_page(
        session,
        slug=repo.DEFAULT_STATUS_PAGE_SLUG,
        title=repo.DEFAULT_STATUS_PAGE_TITLE,
        is_public=True,
        show_response_times=True,
    )
    repo.create_status_page_component(
        session,
        status_page_id=page.id,
        name=repo.DEFAULT_COMPONENT_NAME,
        sort_order=0,
    )
    session.refresh(page)
    return page


def _monitor_runtime_status(monitor: Monitor) -> MonitorPublicStatus:
    if monitor.is_paused:
        return "paused"
    state = monitor.monitor_state
    if state is None or state.last_status is None:
        return "unknown"
    if state.last_status == STATUS_PAUSED:
        return "paused"
    if state.last_status == STATUS_DOWN:
        return "down"
    if state.last_status == STATUS_UP:
        return "up"
    return "unknown"


def aggregate_component_status(monitors: list[Monitor]) -> PublicStatus:
    """
    Aggregate monitor health into a component status.

    Paused monitors are excluded from outage/degraded calculations.
    Empty components or components with only paused monitors return ``unknown``.
    """
    active_statuses = [
        status
        for status in (_monitor_runtime_status(monitor) for monitor in monitors)
        if status != "paused"
    ]
    if not active_statuses:
        return "unknown"
    if any(status == "down" for status in active_statuses):
        return "outage"
    if any(status == "unknown" for status in active_statuses):
        if any(status == "up" for status in active_statuses):
            return "degraded"
        return "unknown"
    return "operational"


def aggregate_overall_status(component_statuses: list[PublicStatus]) -> PublicStatus:
    if not component_statuses:
        return "unknown"
    return max(component_statuses, key=lambda status: STATUS_SEVERITY[status])


def build_public_status_payload(session: Session, page: StatusPage) -> dict[str, object]:
    components_payload: list[dict[str, object]] = []
    component_statuses: list[PublicStatus] = []
    latest_update = page.updated_at

    for component in repo.list_status_page_components(session, page.id):
        monitors = repo.list_component_monitors(session, component.id)
        component_status = aggregate_component_status(monitors)
        component_statuses.append(component_status)

        monitors_payload: list[dict[str, object]] = []
        for monitor in monitors:
            state = monitor.monitor_state
            monitor_status = _monitor_runtime_status(monitor)
            monitor_updated = state.updated_at if state is not None else monitor.updated_at
            if monitor_updated > latest_update:
                latest_update = monitor_updated

            monitor_payload: dict[str, object] = {
                "id": monitor.id,
                "name": monitor.name,
                "status": monitor_status,
                "last_check_at": state.last_check_at if state else None,
            }
            if page.show_response_times:
                monitor_payload["last_response_time_ms"] = (
                    state.last_response_time_ms if state else None
                )
            monitors_payload.append(monitor_payload)

        components_payload.append(
            {
                "id": component.id,
                "name": component.name,
                "status": component_status,
                "monitors": monitors_payload,
            }
        )

    return {
        "title": page.title,
        "slug": page.slug,
        "overall_status": aggregate_overall_status(component_statuses),
        "updated_at": latest_update,
        "components": components_payload,
        "recent_incidents": [],
    }


def build_admin_status_page_payload(session: Session, page: StatusPage) -> dict[str, object]:
    components_payload: list[dict[str, object]] = []
    for component in repo.list_status_page_components(session, page.id):
        monitors = repo.list_component_monitors(session, component.id)
        components_payload.append(
            {
                "id": component.id,
                "name": component.name,
                "sort_order": component.sort_order,
                "monitor_ids": [monitor.id for monitor in monitors],
            }
        )

    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "is_public": page.is_public,
        "show_response_times": page.show_response_times,
        "created_at": page.created_at,
        "updated_at": page.updated_at,
        "components": components_payload,
    }
