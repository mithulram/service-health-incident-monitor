"""Admin status page management routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...auth import require_admin
from ...db.engine import get_session
from ...db import repositories as repo
from ...services.status_pages import build_admin_status_page_payload, ensure_default_status_page

router = APIRouter(prefix="/api/v1/status-page", tags=["status-page"])


class StatusPageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_public: bool | None = None
    show_response_times: bool | None = None


class StatusPageComponentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sort_order: int = Field(default=0, ge=0, le=10_000)


class StatusPageComponentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = Field(default=None, ge=0, le=10_000)


class AdminStatusPageResponse(BaseModel):
    id: int
    slug: str
    title: str
    is_public: bool
    show_response_times: bool
    created_at: datetime
    updated_at: datetime
    components: list[dict[str, object]]


def _load_default_page(session: Session):
    return ensure_default_status_page(session)


@router.get("", response_model=AdminStatusPageResponse, dependencies=[Depends(require_admin)])
def get_status_page(session: Session = Depends(get_session)) -> dict[str, object]:
    page = _load_default_page(session)
    return build_admin_status_page_payload(session, page)


@router.patch("", response_model=AdminStatusPageResponse, dependencies=[Depends(require_admin)])
def update_status_page(
    payload: StatusPageUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        page = repo.update_status_page(session, page, **updates)
    return build_admin_status_page_payload(session, page)


@router.post(
    "/components",
    response_model=AdminStatusPageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_admin)],
)
def create_status_page_component(
    payload: StatusPageComponentCreate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    repo.create_status_page_component(
        session,
        status_page_id=page.id,
        name=payload.name,
        sort_order=payload.sort_order,
    )
    page = repo.update_status_page(session, page)
    return build_admin_status_page_payload(session, page)


@router.patch(
    "/components/{component_id}",
    response_model=AdminStatusPageResponse,
    dependencies=[Depends(require_admin)],
)
def update_status_page_component(
    component_id: int,
    payload: StatusPageComponentUpdate,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    component = repo.get_status_page_component(session, component_id)
    if component is None or component.status_page_id != page.id:
        raise HTTPException(status_code=404, detail="Status page component not found.")
    updates = payload.model_dump(exclude_unset=True)
    if updates:
        repo.update_status_page_component(session, component, **updates)
    page = repo.update_status_page(session, page)
    return build_admin_status_page_payload(session, page)


@router.delete(
    "/components/{component_id}",
    response_model=AdminStatusPageResponse,
    dependencies=[Depends(require_admin)],
)
def delete_status_page_component(
    component_id: int,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    component = repo.get_status_page_component(session, component_id)
    if component is None or component.status_page_id != page.id:
        raise HTTPException(status_code=404, detail="Status page component not found.")
    repo.delete_status_page_component(session, component)
    page = repo.update_status_page(session, page)
    return build_admin_status_page_payload(session, page)


@router.post(
    "/components/{component_id}/monitors/{monitor_id}",
    response_model=AdminStatusPageResponse,
    dependencies=[Depends(require_admin)],
)
def add_monitor_to_status_component(
    component_id: int,
    monitor_id: int,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    component = repo.get_status_page_component(session, component_id)
    if component is None or component.status_page_id != page.id:
        raise HTTPException(status_code=404, detail="Status page component not found.")

    monitor = repo.get_monitor(session, monitor_id)
    if monitor is None:
        raise HTTPException(status_code=404, detail="Monitor not found.")

    existing = repo.get_component_monitor_link(session, component_id, monitor_id)
    if existing is None:
        repo.add_monitor_to_component(session, component_id, monitor_id)

    page = repo.update_status_page(session, page)
    return build_admin_status_page_payload(session, page)


@router.delete(
    "/components/{component_id}/monitors/{monitor_id}",
    response_model=AdminStatusPageResponse,
    dependencies=[Depends(require_admin)],
)
def remove_monitor_from_status_component(
    component_id: int,
    monitor_id: int,
    session: Session = Depends(get_session),
) -> dict[str, object]:
    page = _load_default_page(session)
    component = repo.get_status_page_component(session, component_id)
    if component is None or component.status_page_id != page.id:
        raise HTTPException(status_code=404, detail="Status page component not found.")

    link = repo.get_component_monitor_link(session, component_id, monitor_id)
    if link is not None:
        repo.remove_monitor_from_component(session, link)

    page = repo.update_status_page(session, page)
    return build_admin_status_page_payload(session, page)
