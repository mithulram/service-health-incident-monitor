import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

import support  # noqa: F401
from support import test_database_url
from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.db.engine import session_scope
from service_monitor.db import repositories as repo
from service_monitor.services.status_pages import ensure_default_status_page
from service_monitor.state import MonitorState


MEMORY_DB = test_database_url()
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}
ADMIN_HEADERS = {"Authorization": "Bearer expected-secret"}


def make_client(
    *,
    demo_mode: bool = True,
    admin_api_key: str | None = None,
    database_url: str = MEMORY_DB,
) -> TestClient:
    settings = Settings(
        demo_mode=demo_mode,
        admin_api_key=admin_api_key,
        database_url=database_url,
    )
    return TestClient(create_app(MonitorState(), settings=settings))


class StatusPageApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()

    def test_public_status_endpoint_is_accessible_without_auth(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")

        response = client.get("/api/public/v1/status/default")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], "default")
        self.assertEqual(payload["title"], "Service Status")
        self.assertIn(payload["overall_status"], {"operational", "degraded", "outage", "unknown"})
        self.assertEqual(payload["recent_incidents"], [])

    def test_admin_status_page_requires_auth(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")

        response = client.get("/api/v1/status-page")
        self.assertEqual(response.status_code, 401)

        authorized = client.get("/api/v1/status-page", headers=ADMIN_HEADERS)
        self.assertEqual(authorized.status_code, 200)
        self.assertEqual(authorized.json()["slug"], "default")

    def test_default_page_is_created_idempotently(self):
        client = make_client()

        first = client.get("/api/public/v1/status/default")
        second = client.get("/api/public/v1/status/default")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

        with session_scope() as session:
            from sqlalchemy import select

            from service_monitor.db.models import StatusPage

            page = repo.get_default_status_page(session)
            self.assertIsNotNone(page)
            components = repo.list_status_page_components(session, page.id)
            self.assertEqual(len(components), 1)
            self.assertEqual(components[0].name, repo.DEFAULT_COMPONENT_NAME)

            ensure_default_status_page(session)
            all_pages = list(session.scalars(select(StatusPage)).all())
            self.assertEqual(len(all_pages), 1)

    def test_adding_monitor_to_component_appears_in_public_json(self):
        client = make_client()

        create_response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR)
        monitor_id = create_response.json()["id"]

        admin_page = client.get("/api/v1/status-page").json()
        component_id = admin_page["components"][0]["id"]

        add_response = client.post(f"/api/v1/status-page/components/{component_id}/monitors/{monitor_id}")
        self.assertEqual(add_response.status_code, 200)

        public_response = client.get("/api/public/v1/status/default")
        self.assertEqual(public_response.status_code, 200)
        monitors = public_response.json()["components"][0]["monitors"]
        self.assertEqual(len(monitors), 1)
        self.assertEqual(monitors[0]["id"], monitor_id)
        self.assertEqual(monitors[0]["name"], PUBLIC_MONITOR["name"])

    def test_down_monitor_makes_component_and_overall_status_outage(self):
        client = make_client()

        create_response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR)
        monitor_id = create_response.json()["id"]
        component_id = client.get("/api/v1/status-page").json()["components"][0]["id"]
        client.post(f"/api/v1/status-page/components/{component_id}/monitors/{monitor_id}")

        mock_http = mock.Mock()
        mock_http.__enter__ = mock.Mock(return_value=mock_http)
        mock_http.__exit__ = mock.Mock(return_value=False)
        mock_http.request.return_value = httpx.Response(503)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            run_response = client.post(f"/api/v1/checks/run/{monitor_id}")
            self.assertEqual(run_response.status_code, 200)

        public_response = client.get("/api/public/v1/status/default")
        payload = public_response.json()
        self.assertEqual(payload["components"][0]["status"], "outage")
        self.assertEqual(payload["overall_status"], "outage")
        self.assertEqual(payload["components"][0]["monitors"][0]["status"], "down")

    def test_show_response_times_false_hides_response_times_publicly(self):
        client = make_client()

        create_response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR)
        monitor_id = create_response.json()["id"]
        component_id = client.get("/api/v1/status-page").json()["components"][0]["id"]
        client.post(f"/api/v1/status-page/components/{component_id}/monitors/{monitor_id}")

        mock_http = mock.Mock()
        mock_http.__enter__ = mock.Mock(return_value=mock_http)
        mock_http.__exit__ = mock.Mock(return_value=False)
        mock_http.request.return_value = httpx.Response(200)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            client.post(f"/api/v1/checks/run/{monitor_id}")

        patch_response = client.patch(
            "/api/v1/status-page",
            json={"show_response_times": False},
        )
        self.assertEqual(patch_response.status_code, 200)

        public_response = client.get("/api/public/v1/status/default")
        monitor_payload = public_response.json()["components"][0]["monitors"][0]
        self.assertNotIn("last_response_time_ms", monitor_payload)

    def test_empty_component_returns_unknown_status(self):
        client = make_client()

        public_response = client.get("/api/public/v1/status/default")
        payload = public_response.json()
        self.assertEqual(payload["components"][0]["status"], "unknown")
        self.assertEqual(payload["overall_status"], "unknown")

    def test_paused_monitor_does_not_create_outage(self):
        client = make_client()

        create_response = client.post(
            "/api/v1/monitors",
            json={**PUBLIC_MONITOR, "is_paused": True},
        )
        monitor_id = create_response.json()["id"]
        component_id = client.get("/api/v1/status-page").json()["components"][0]["id"]
        client.post(f"/api/v1/status-page/components/{component_id}/monitors/{monitor_id}")

        public_response = client.get("/api/public/v1/status/default")
        payload = public_response.json()
        self.assertEqual(payload["components"][0]["status"], "unknown")
        self.assertEqual(payload["components"][0]["monitors"][0]["status"], "paused")


if __name__ == "__main__":
    unittest.main()
