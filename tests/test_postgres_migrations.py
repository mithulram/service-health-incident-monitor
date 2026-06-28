"""Postgres migration and integration checks for CI."""

from __future__ import annotations

import unittest
from unittest import mock

import httpx
from fastapi.testclient import TestClient

from service_monitor.app import create_app
from service_monitor.config import Settings
from service_monitor.state import MonitorState
from support import test_database_url, uses_postgres

PUBLIC_MONITOR = {
    "name": "Postgres integration API",
    "url": "https://example.com/health",
    "method": "GET",
}


class PostgresMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        if not uses_postgres():
            self.skipTest("DATABASE_URL must point at Postgres for this job")

        self.getaddrinfo_patcher = mock.patch(
            "service_monitor.ssrf.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 443))],
        )
        self.getaddrinfo_patcher.start()

    def tearDown(self) -> None:
        self.getaddrinfo_patcher.stop()

    def make_client(self, *, demo_mode: bool = True) -> TestClient:
        settings = Settings(demo_mode=demo_mode, database_url=test_database_url())
        return TestClient(create_app(MonitorState(), settings=settings))

    def test_readyz_reports_database_ready(self) -> None:
        client = self.make_client()
        response = client.get("/readyz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ready"})

    def test_monitor_crud_round_trip_on_postgres(self) -> None:
        client = self.make_client()

        create_response = client.post("/api/v1/monitors", json=PUBLIC_MONITOR)
        self.assertEqual(create_response.status_code, 201)
        monitor_id = create_response.json()["id"]

        list_response = client.get("/api/v1/monitors")
        self.assertEqual(list_response.status_code, 200)
        self.assertGreaterEqual(len(list_response.json()), 1)

        delete_response = client.delete(f"/api/v1/monitors/{monitor_id}")
        self.assertEqual(delete_response.status_code, 204)

    def test_public_status_page_json_on_postgres(self) -> None:
        client = self.make_client()
        response = client.get("/api/public/v1/status/default")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], "default")
        self.assertIn("components", payload)

    def test_manual_check_persists_history_on_postgres(self) -> None:
        client = self.make_client()
        monitor = client.post("/api/v1/monitors", json=PUBLIC_MONITOR).json()
        mock_http = mock.Mock()
        mock_http.request.return_value = httpx.Response(200)

        with mock.patch("service_monitor.services.checks.httpx.Client", return_value=mock_http):
            run_response = client.post(f"/api/v1/checks/run/{monitor['id']}")

        self.assertEqual(run_response.status_code, 200)
        history = client.get(f"/api/v1/monitors/{monitor['id']}/checks").json()
        self.assertEqual(len(history), 1)

        client.delete(f"/api/v1/monitors/{monitor['id']}")
