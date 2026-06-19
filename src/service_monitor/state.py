"""Thread-safe operational state and SLO calculations for the demo service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from threading import Lock


@dataclass(frozen=True)
class Incident:
    identifier: str
    service: str
    severity: str
    status: str
    summary: str
    started_at: str


class MonitorState:
    """A small, explicit in-memory model suitable for a local operational demo."""

    def __init__(self, *, success_count: int = 399, failure_count: int = 1) -> None:
        self._success_count = success_count
        self._failure_count = failure_count
        self._request_count = success_count + failure_count
        self._lock = Lock()
        self._incidents = [
            Incident(
                identifier="INC-1042",
                service="checkout-api",
                severity="SEV-2",
                status="OPEN",
                summary="Elevated p95 latency after a downstream inventory timeout spike.",
                started_at="2026-06-19T08:14:00Z",
            ),
            Incident(
                identifier="INC-1039",
                service="notification-worker",
                severity="SEV-3",
                status="RESOLVED",
                summary="Queue consumer restart recovered delayed email delivery.",
                started_at="2026-06-18T15:26:00Z",
            ),
        ]

    def record_request(self, status_code: int) -> None:
        with self._lock:
            self._request_count += 1
            if status_code >= 500:
                self._failure_count += 1
            else:
                self._success_count += 1

    def summary(self) -> dict[str, float | int]:
        with self._lock:
            availability = self._success_count / self._request_count if self._request_count else 1.0
            slo_target = 0.995
            allowed_failure_rate = 1 - slo_target
            observed_failure_rate = 1 - availability
            error_budget_remaining = max(0.0, (allowed_failure_rate - observed_failure_rate) / allowed_failure_rate)
            return {
                "requests_total": self._request_count,
                "requests_successful": self._success_count,
                "requests_failed": self._failure_count,
                "availability_ratio": round(availability, 6),
                "slo_target_ratio": slo_target,
                "error_budget_remaining_ratio": round(error_budget_remaining, 6),
                "open_incident_count": sum(incident.status == "OPEN" for incident in self._incidents),
            }

    def incidents(self) -> list[dict[str, str]]:
        return [asdict(incident) for incident in self._incidents]

    def prometheus_metrics(self) -> str:
        summary = self.summary()
        return "\n".join(
            (
                "# HELP service_requests_total Synthetic requests observed by the monitor.",
                "# TYPE service_requests_total counter",
                f'service_requests_total{{status_class="2xx_4xx"}} {summary["requests_successful"]}',
                f'service_requests_total{{status_class="5xx"}} {summary["requests_failed"]}',
                "# HELP service_slo_availability_ratio Availability calculated from observed response classes.",
                "# TYPE service_slo_availability_ratio gauge",
                f'service_slo_availability_ratio {summary["availability_ratio"]}',
                "# HELP service_slo_error_budget_remaining_ratio Remaining process-lifetime synthetic error-budget ratio for a 99.5 percent target.",
                "# TYPE service_slo_error_budget_remaining_ratio gauge",
                f'service_slo_error_budget_remaining_ratio {summary["error_budget_remaining_ratio"]}',
                "# HELP service_incidents_open Count of currently open synthetic incidents.",
                "# TYPE service_incidents_open gauge",
                f'service_incidents_open {summary["open_incident_count"]}',
                "",
            )
        )

    @staticmethod
    def event_timestamp() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
