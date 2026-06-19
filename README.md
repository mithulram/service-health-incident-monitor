# Service Health & Incident Monitor

A runnable FastAPI service that models the operational concerns behind a cloud/platform role: health checks, Prometheus-compatible metrics, availability SLOs, error budgets, incidents, structured event logging, and a small dashboard backed by live API endpoints.

> **Scope note:** This project intentionally uses synthetic in-memory service events. It demonstrates how operational signals are exposed and reasoned about; it is not an actual production monitoring platform.

![Operational dashboard preview](docs/screenshots/monitor-dashboard.png)

## What it demonstrates

- FastAPI HTTP service design, typed request validation, and live API testing.
- Separate liveness (`/healthz`) and readiness (`/readyz`) endpoints.
- Availability SLO and **process-lifetime synthetic** error-budget calculation for a 99.5% target.
- Prometheus 0.0.4 text-format metrics at `/metrics`, with HELP/TYPE metadata and a valid text content type.
- Incident context alongside quantitative signals, including open and resolved incidents.
- A synthetic fault-injection endpoint used to prove that service errors consume the calculated error budget.
- A browser dashboard that fetches live service data, not a static mock-up.

## Run locally

Requirements: Python 3.11+.

```bash
git clone https://github.com/mithulram/service-health-incident-monitor.git
cd service-health-incident-monitor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[test]'
DEMO_MODE=true uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090
```

Visit [http://127.0.0.1:8090](http://127.0.0.1:8090) for the dashboard. API documentation is available at `/docs`.

## Endpoint contract

| Endpoint | Purpose |
|---|---|
| `GET /healthz` | Lightweight liveness signal |
| `GET /readyz` | Readiness signal |
| `GET /api/v1/summary` | Request counts, availability, SLO target, error budget, open-incident count |
| `GET /api/v1/slo` | SLO-focused summary |
| `GET /api/v1/incidents` | Synthetic incident context |
| `POST /api/v1/simulate/request` | Record a synthetic status code when `DEMO_MODE=true` (disabled otherwise) |
| `GET /metrics` | Prometheus text-format metrics |

## Operational model

The monitor starts with 399 successful responses and 1 server error: 99.75% availability. For a 99.5% SLO target, that leaves 50% of the **process-lifetime synthetic** error budget. Recording a `5xx` response through the simulation endpoint lowers availability and consumes more of that budget. The calculation covers the in-memory lifetime of the demo process, not a calendar month.

```bash
DEMO_MODE=true uvicorn service_monitor.app:app --host 127.0.0.1 --port 8090

curl -X POST http://127.0.0.1:8090/api/v1/simulate/request \
  -H 'Content-Type: application/json' \
  -d '{"status_code":503}'

curl http://127.0.0.1:8090/metrics
```

## Verify

```bash
python -m unittest discover -s tests -v
python -m compileall -q src tests
```

The test suite checks health/readiness, SLO values, Prometheus response semantics, incident data, and that an injected `503` reduces error-budget headroom.

## Design boundaries

- Data is in-memory so a fresh clone runs immediately; a production implementation would source events from logs, traces, or a metrics backend.
- The metrics output follows Prometheus's human-readable text exposition style but does not replace a Prometheus server, alert manager, or dashboard platform.
- The `simulate` endpoint is intentionally a demo/testing hook and would not be publicly exposed in production.

## Resume-ready description

> Built a FastAPI service-health monitor that exposes readiness and Prometheus-format metrics, calculates a 99.5% availability SLO and error budget, correlates incidents with operational signals, and verifies fault-injection effects through HTTP tests.

## License

MIT. See [LICENSE](LICENSE).
