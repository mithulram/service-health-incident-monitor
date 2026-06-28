import unittest

from fastapi.testclient import TestClient

import support  # noqa: F401
from support import test_database_url
from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.db.engine import session_scope
from service_monitor.db import repositories as repo
from service_monitor.services.public_demo import SAMPLE_REASON
from service_monitor.state import MonitorState


MEMORY_DB = test_database_url()
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}
ADMIN_HEADERS = {"Authorization": "Bearer expected-secret"}


def make_client(**settings_overrides: object) -> TestClient:
    defaults = {
        "demo_mode": False,
        "admin_api_key": "expected-secret",
        "database_url": MEMORY_DB,
    }
    defaults.update(settings_overrides)
    settings = Settings(**defaults)
    return TestClient(create_app(MonitorState(), settings=settings, database_url=settings.database_url))


class PublicDemoTests(unittest.TestCase):
    def test_empty_database_summary_returns_sample_markers_and_fleet_preview(self):
        client = make_client()
        payload = client.get("/api/v1/summary").json()

        self.assertTrue(payload["is_sample_data"])
        self.assertEqual(payload["sample_reason"], SAMPLE_REASON)
        self.assertEqual(payload["monitors_total"], 3)
        self.assertEqual(payload["monitors_up"], 2)
        self.assertEqual(payload["monitors_paused"], 1)
        self.assertEqual(payload["average_response_time_ms_24h"], 142.5)
        self.assertIn("requests_total", payload)
        self.assertIn("availability_ratio", payload)

    def test_empty_database_incidents_return_sample_items_without_db_rows(self):
        client = make_client()
        incidents = client.get("/api/v1/incidents").json()

        self.assertEqual(len(incidents), 2)
        self.assertTrue(all(item["is_sample"] for item in incidents))
        self.assertTrue(all(item["identifier"].startswith("SAMPLE-") for item in incidents))

        with session_scope() as session:
            self.assertEqual(repo.count_incidents(session), 0)
            self.assertEqual(repo.count_monitors(session), 0)

    def test_empty_database_public_status_returns_sample_preview_without_urls(self):
        client = make_client()
        payload = client.get("/api/public/v1/status/default").json()

        self.assertTrue(payload["is_sample_data"])
        self.assertEqual(payload["sample_reason"], SAMPLE_REASON)
        self.assertEqual(payload["recent_incidents"], [])
        self.assertGreater(len(payload["components"]), 0)
        for component in payload["components"]:
            self.assertTrue(component["is_sample"])
            for monitor in component["monitors"]:
                self.assertTrue(monitor["is_sample"])
                self.assertNotIn("url", monitor)

    def test_real_monitor_data_removes_sample_markers(self):
        client = make_client()
        client.post("/api/v1/monitors", json=PUBLIC_MONITOR, headers=ADMIN_HEADERS)

        summary = client.get("/api/v1/summary").json()
        incidents = client.get("/api/v1/incidents").json()
        status = client.get("/api/public/v1/status/default").json()

        self.assertNotIn("is_sample_data", summary)
        self.assertEqual(incidents, [])
        self.assertNotIn("is_sample_data", status)

    def test_protected_routes_remain_locked_with_demo_mode_false(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")

        self.assertEqual(client.get("/api/v1/monitors").status_code, 401)
        self.assertEqual(client.get("/api/v1/status-page").status_code, 401)
        self.assertEqual(client.get("/api/v1/settings/alerts").status_code, 401)

        authorized = client.get("/api/v1/monitors", headers=ADMIN_HEADERS)
        self.assertEqual(authorized.status_code, 200)


if __name__ == "__main__":
    unittest.main()
