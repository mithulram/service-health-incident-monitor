"""Public status page routes."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...db.engine import get_session
from ...db import repositories as repo
from ...services.public_demo import sample_public_status_payload, should_use_public_sample_data
from ...services.status_pages import build_public_status_payload, ensure_default_status_page

router = APIRouter(prefix="/api/public/v1", tags=["public-status"])


class PublicMonitorStatus(BaseModel):
    id: int
    name: str
    status: str
    last_check_at: datetime | None = None
    last_response_time_ms: int | None = None


class PublicComponentStatus(BaseModel):
    id: int
    name: str
    status: str
    monitors: list[PublicMonitorStatus]


class PublicStatusPageResponse(BaseModel):
    title: str
    slug: str
    overall_status: str
    updated_at: datetime
    components: list[PublicComponentStatus]
    recent_incidents: list[dict[str, object]]


@router.get("/status/{slug}")
def get_public_status_page(slug: str, session: Session = Depends(get_session)) -> dict[str, object]:
    ensure_default_status_page(session)
    page = repo.get_status_page_by_slug(session, slug)
    if page is None:
        raise HTTPException(status_code=404, detail="Status page not found.")
    if not page.is_public:
        raise HTTPException(status_code=404, detail="Status page not found.")
    if should_use_public_sample_data(session):
        return sample_public_status_payload(page)
    return build_public_status_payload(session, page)
