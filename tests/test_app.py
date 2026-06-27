import os
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from service_monitor.app import create_app
from service_monitor.state import MonitorState


STATIC_DIR = Path(__file__).resolve().parents[1] / "src" / "service_monitor" / "static"


class ServiceMonitorTests(unittest.TestCase):
    def test_fresh_monitor_starts_with_documented_request_counts(self):
        summary = MonitorState().summary()
        self.assertEqual(summary["requests_successful"], 399)
        self.assertEqual(summary["requests_failed"], 1)
        self.assertEqual(summary["requests_total"], 400)

    def test_health_and_readiness_are_available(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        self.assertEqual(client.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(client.get("/readyz").json(), {"status": "ready"})

    def test_summary_exposes_slo_and_error_budget(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        payload = client.get("/api/v1/summary").json()
        self.assertEqual(payload["slo_target_ratio"], 0.995)
        self.assertGreater(payload["availability_ratio"], payload["slo_target_ratio"])
        self.assertGreater(payload["error_budget_remaining_ratio"], 0)
        self.assertEqual(payload["open_incident_count"], 1)

    def test_metrics_use_process_lifetime_error_budget_wording(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        response = client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("# HELP service_requests_total", response.text)
        self.assertIn("process-lifetime synthetic error-budget", response.text)
        self.assertNotIn("monthly error-budget", response.text)
        self.assertTrue(response.text.endswith("\n"))

    def test_simulated_server_error_reduces_error_budget(self):
        client = TestClient(create_app(MonitorState(), demo_mode=True, database_url="sqlite:///:memory:"))
        before = client.get("/api/v1/slo").json()["error_budget_remaining_ratio"]
        response = client.post("/api/v1/simulate/request", json={"status_code": 503})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recorded_status_code"], 503)
        after = client.get("/api/v1/slo").json()["error_budget_remaining_ratio"]
        self.assertLess(after, before)

    def test_simulated_non_5xx_increments_success_count(self):
        client = TestClient(create_app(MonitorState(), demo_mode=True, database_url="sqlite:///:memory:"))
        before = client.get("/api/v1/summary").json()["requests_successful"]
        response = client.post("/api/v1/simulate/request", json={"status_code": 200})
        self.assertEqual(response.status_code, 200)
        after = client.get("/api/v1/summary").json()["requests_successful"]
        self.assertEqual(after, before + 1)

    def test_simulation_is_disabled_without_demo_mode(self):
        client = TestClient(create_app(MonitorState(), demo_mode=False, database_url="sqlite:///:memory:"))
        response = client.post("/api/v1/simulate/request", json={"status_code": 503})
        self.assertEqual(response.status_code, 403)

    def test_isolated_apps_do_not_share_simulation_state(self):
        client_a = TestClient(create_app(MonitorState(), demo_mode=True, database_url="sqlite:///:memory:"))
        client_b = TestClient(create_app(MonitorState(), demo_mode=True, database_url="sqlite:///:memory:"))
        before_b = client_b.get("/api/v1/summary").json()["requests_total"]
        client_a.post("/api/v1/simulate/request", json={"status_code": 503})
        after_b = client_b.get("/api/v1/summary").json()["requests_total"]
        self.assertEqual(before_b, after_b)

    def test_incidents_include_open_and_resolved_context(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        incidents = client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 2)
        self.assertEqual(incidents[0]["status"], "OPEN")
        self.assertEqual(incidents[1]["status"], "RESOLVED")

    def test_dashboard_builds_incident_rows_without_inner_html(self):
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(".innerHTML", html)
        self.assertIn("createElement", html)
        self.assertIn("textContent", html)

    def test_cors_allows_local_dev_origin(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        response = client.options(
            "/api/v1/summary",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_cors_rejects_unknown_origin(self):
        client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
        response = client.options(
            "/api/v1/summary",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_cors_uses_web_cors_origins_env_var(self):
        with mock.patch.dict(
            os.environ,
            {"WEB_CORS_ORIGINS": "https://dashboard.example.com,https://www.example.com"},
        ):
            client = TestClient(create_app(MonitorState(), database_url="sqlite:///:memory:"))
            response = client.options(
                "/api/v1/summary",
                headers={
                    "Origin": "https://dashboard.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "https://dashboard.example.com",
        )
        self.assertNotEqual(
            client.options(
                "/api/v1/summary",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                },
            ).headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )
