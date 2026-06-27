"""Outbound HTTP check execution for persisted monitors."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from ..db.models import Monitor
from ..ssrf import SSRFError, validate_monitor_url


@dataclass(frozen=True)
class CheckOutcome:
    checked_at: datetime
    status_code: int | None
    response_time_ms: int | None
    success: bool
    error_message: str | None


def _evaluate_success(monitor: Monitor, status_code: int | None) -> bool:
    if status_code is None:
        return False
    return monitor.expected_status_min <= status_code <= monitor.expected_status_max


def run_monitor_check(monitor: Monitor, *, client: httpx.Client | None = None) -> CheckOutcome:
    """Execute a single monitor check and return the outcome."""
    checked_at = datetime.now(UTC)

    try:
        validate_monitor_url(monitor.url)
    except SSRFError as exc:
        return CheckOutcome(
            checked_at=checked_at,
            status_code=None,
            response_time_ms=None,
            success=False,
            error_message=str(exc),
        )

    owns_client = client is None
    http_client = client or httpx.Client(follow_redirects=True)

    try:
        started = time.perf_counter()
        response = http_client.request(
            monitor.method,
            monitor.url,
            timeout=monitor.timeout_seconds,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        success = _evaluate_success(monitor, response.status_code)
        error_message = None
        if not success:
            error_message = (
                f"Unexpected status code {response.status_code}; "
                f"expected {monitor.expected_status_min}-{monitor.expected_status_max}."
            )
        return CheckOutcome(
            checked_at=checked_at,
            status_code=response.status_code,
            response_time_ms=elapsed_ms,
            success=success,
            error_message=error_message,
        )
    except httpx.TimeoutException:
        return CheckOutcome(
            checked_at=checked_at,
            status_code=None,
            response_time_ms=None,
            success=False,
            error_message="Request timed out.",
        )
    except httpx.ConnectError as exc:
        return CheckOutcome(
            checked_at=checked_at,
            status_code=None,
            response_time_ms=None,
            success=False,
            error_message=f"Connection error: {exc}",
        )
    except httpx.RequestError as exc:
        message = str(exc)
        lowered = message.lower()
        if "ssl" in lowered or "tls" in lowered or "certificate" in lowered:
            error_message = f"TLS error: {exc}"
        else:
            error_message = f"Request error: {exc}"
        return CheckOutcome(
            checked_at=checked_at,
            status_code=None,
            response_time_ms=None,
            success=False,
            error_message=error_message,
        )
    finally:
        if owns_client:
            http_client.close()
