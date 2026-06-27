"""FastAPI application exposing health, SLO, incident, and metrics endpoints."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .api.v1.monitors import router as monitors_router
from .config import Settings, clear_settings_cache, cors_origins_from_settings, get_settings
from .db.engine import check_database_connection, create_all_tables, dispose_engine, init_engine, session_scope
from .scheduler import MonitorScheduler
from .services.fleet import fleet_summary
from .state import MonitorState


LOGGER = logging.getLogger("service_monitor")
STATIC_DIR = Path(__file__).parent / "static"


class RequestSimulation(BaseModel):
    status_code: int = Field(ge=100, le=599, examples=[503])


def create_app(
    monitor_state: MonitorState | None = None,
    *,
    demo_mode: bool | None = None,
    database_url: str | None = None,
    settings: Settings | None = None,
    scheduler_enabled: bool | None = None,
) -> FastAPI:
    """Build a FastAPI app bound to an isolated monitor state instance."""
    clear_settings_cache()
    if settings is not None:
        resolved_settings = settings
    else:
        resolved_settings = get_settings()

    updates: dict[str, object] = {}
    if demo_mode is not None:
        updates["demo_mode"] = demo_mode
    if scheduler_enabled is not None:
        updates["scheduler_enabled"] = scheduler_enabled
    if updates:
        resolved_settings = resolved_settings.model_copy(update=updates)

    state = monitor_state if monitor_state is not None else MonitorState()
    simulation_enabled = resolved_settings.demo_mode
    db_url = database_url or resolved_settings.database_url

    init_engine(db_url)
    create_all_tables()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.settings = resolved_settings
        scheduler = MonitorScheduler(resolved_settings)
        application.state.monitor_scheduler = scheduler
        scheduler.start()
        yield
        scheduler.shutdown()
        dispose_engine()

    application = FastAPI(
        title="Service Health & Incident Monitor",
        version="0.3.0",
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins_from_settings(resolved_settings),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )
    application.include_router(monitors_router)

    @application.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readiness() -> dict[str, str]:
        if not check_database_connection():
            raise HTTPException(status_code=503, detail="Database is not ready.")
        return {"status": "ready"}

    @application.get("/api/v1/summary")
    def summary() -> dict[str, float | int | None]:
        payload: dict[str, float | int | None] = dict(state.summary())
        with session_scope() as session:
            payload.update(fleet_summary(session))
        return payload

    @application.get("/api/v1/slo")
    def slo() -> dict[str, float | int]:
        summary_payload = state.summary()
        return {
            "availability_ratio": summary_payload["availability_ratio"],
            "slo_target_ratio": summary_payload["slo_target_ratio"],
            "error_budget_remaining_ratio": summary_payload["error_budget_remaining_ratio"],
        }

    @application.get("/api/v1/incidents")
    def incidents() -> list[dict[str, str]]:
        return state.incidents()

    @application.post("/api/v1/simulate/request")
    def simulate_request(event: RequestSimulation) -> dict[str, float | int | str]:
        if not simulation_enabled:
            raise HTTPException(
                status_code=403,
                detail="Request simulation is disabled. Set DEMO_MODE=true for local demo use.",
            )
        state.record_request(event.status_code)
        LOGGER.info(
            "event=request_simulated status_code=%s timestamp=%s",
            event.status_code,
            state.event_timestamp(),
        )
        return {"recorded_status_code": event.status_code, **state.summary()}

    @application.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            state.prometheus_metrics(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return application


app = create_app()
