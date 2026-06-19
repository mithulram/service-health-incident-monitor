"""FastAPI application exposing health, SLO, incident, and metrics endpoints."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .state import MonitorState


LOGGER = logging.getLogger("service_monitor")
STATIC_DIR = Path(__file__).parent / "static"


class RequestSimulation(BaseModel):
    status_code: int = Field(ge=100, le=599, examples=[503])


def demo_mode_enabled(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")


def create_app(
    monitor_state: MonitorState | None = None,
    *,
    demo_mode: bool | None = None,
) -> FastAPI:
    """Build a FastAPI app bound to an isolated monitor state instance."""
    state = monitor_state if monitor_state is not None else MonitorState()
    simulation_enabled = demo_mode_enabled(demo_mode)

    application = FastAPI(title="Service Health & Incident Monitor", version="0.1.0")

    @application.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @application.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readiness() -> dict[str, str]:
        return {"status": "ready"}

    @application.get("/api/v1/summary")
    def summary() -> dict[str, float | int]:
        return state.summary()

    @application.get("/api/v1/slo")
    def slo() -> dict[str, float | int]:
        summary = state.summary()
        return {
            "availability_ratio": summary["availability_ratio"],
            "slo_target_ratio": summary["slo_target_ratio"],
            "error_budget_remaining_ratio": summary["error_budget_remaining_ratio"],
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
