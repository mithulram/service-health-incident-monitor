import unittest

from fastapi.testclient import TestClient

from service_monitor.app import app, state


class ServiceMonitorTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_and_readiness_are_available(self):
        self.assertEqual(self.client.get("/healthz").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/readyz").json(), {"status": "ready"})

    def test_summary_exposes_slo_and_error_budget(self):
        payload = self.client.get("/api/v1/summary").json()
        self.assertEqual(payload["slo_target_ratio"], 0.995)
        self.assertGreater(payload["availability_ratio"], payload["slo_target_ratio"])
        self.assertGreater(payload["error_budget_remaining_ratio"], 0)
        self.assertEqual(payload["open_incident_count"], 1)

    def test_metrics_follow_prometheus_text_conventions(self):
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("# HELP service_requests_total", response.text)
        self.assertIn("# TYPE service_slo_availability_ratio gauge", response.text)
        self.assertTrue(response.text.endswith("\n"))

    def test_simulated_server_error_reduces_error_budget(self):
        before = self.client.get("/api/v1/slo").json()["error_budget_remaining_ratio"]
        response = self.client.post("/api/v1/simulate/request", json={"status_code": 503})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["recorded_status_code"], 503)
        after = self.client.get("/api/v1/slo").json()["error_budget_remaining_ratio"]
        self.assertLess(after, before)

    def test_incidents_include_open_and_resolved_context(self):
        incidents = self.client.get("/api/v1/incidents").json()
        self.assertEqual(len(incidents), 2)
        self.assertEqual(incidents[0]["status"], "OPEN")
        self.assertEqual(incidents[1]["status"], "RESOLVED")
