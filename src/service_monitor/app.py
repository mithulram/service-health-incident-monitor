"""FastAPI application exposing health, SLO, incident, and metrics endpoints."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .state import MonitorState


LOGGER = logging.getLogger("service_monitor")
STATIC_DIR = Path(__file__).parent / "static"
state = MonitorState()
app = FastAPI(title="Service Health & Incident Monitor", version="0.1.0")


class RequestSimulation(BaseModel):
    status_code: int = Field(ge=100, le=599, examples=[503])


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readiness() -> dict[str, str]:
    return {"status": "ready"}


@app.get("/api/v1/summary")
def summary() -> dict[str, float | int]:
    return state.summary()


@app.get("/api/v1/slo")
def slo() -> dict[str, float | int]:
    summary = state.summary()
    return {
        "availability_ratio": summary["availability_ratio"],
        "slo_target_ratio": summary["slo_target_ratio"],
        "error_budget_remaining_ratio": summary["error_budget_remaining_ratio"],
    }


@app.get("/api/v1/incidents")
def incidents() -> list[dict[str, str]]:
    return state.incidents()


@app.post("/api/v1/simulate/request")
def simulate_request(event: RequestSimulation) -> dict[str, float | int | str]:
    state.record_request(event.status_code)
    LOGGER.info("event=request_simulated status_code=%s timestamp=%s", event.status_code, state.event_timestamp())
    return {"recorded_status_code": event.status_code, **state.summary()}


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        state.prometheus_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
