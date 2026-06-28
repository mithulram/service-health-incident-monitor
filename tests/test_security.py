import unittest
from unittest import mock

from fastapi.testclient import TestClient

import support  # noqa: F401
from support import test_database_url
from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.state import MonitorState


MEMORY_DB = test_database_url()
PUBLIC_MONITOR = {
    "name": "Example API",
    "url": "https://example.com/health",
    "method": "GET",
}


def make_client(
    *,
    demo_mode: bool,
    admin_api_key: str | None = None,
) -> TestClient:
    settings = Settings(
        demo_mode=demo_mode,
        admin_api_key=admin_api_key,
        database_url=MEMORY_DB,
    )
    return TestClient(create_app(MonitorState(), settings=settings))


class ProductionSecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()

    def test_demo_mode_allows_protected_routes_without_admin_key(self):
        client = make_client(demo_mode=True, admin_api_key=None)
        response = client.get("/api/v1/monitors")
        self.assertEqual(response.status_code, 200)

    def test_production_rejects_protected_routes_without_admin_key(self):
        client = make_client(demo_mode=False, admin_api_key=None)
        response = client.get("/api/v1/monitors")
        self.assertEqual(response.status_code, 503)

    def test_production_requires_bearer_token_when_admin_key_set(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")

        unauthorized = client.get("/api/v1/monitors")
        self.assertEqual(unauthorized.status_code, 401)

        authorized = client.get(
            "/api/v1/monitors",
            headers={"Authorization": "Bearer expected-secret"},
        )
        self.assertEqual(authorized.status_code, 200)

    def test_simulate_endpoint_disabled_when_demo_mode_false(self):
        client = make_client(demo_mode=False, admin_api_key="expected-secret")
        response = client.post("/api/v1/simulate/request", json={"status_code": 503})
        self.assertEqual(response.status_code, 403)
