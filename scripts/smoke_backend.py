#!/usr/bin/env python3
"""Smoke test a deployed Service Health & Incident Monitor backend."""

from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request

ENDPOINTS = (
    "/healthz",
    "/readyz",
    "/api/v1/summary",
    "/api/v1/incidents",
    "/api/public/v1/status/default",
    "/metrics",
)
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}
PROTECTED_DENY_STATUSES = {401, 403, 503}


def preview_body(body: bytes, max_length: int = 120) -> str:
    text = " ".join(body.decode("utf-8", errors="replace").split())
    if not text:
        return "(empty body)"
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def should_retry_status(status: int) -> bool:
    return status in RETRYABLE_STATUS_CODES


def request_with_retry(
    label: str,
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    expected_status: int | set[int] | None = None,
) -> tuple[int, bytes]:
    request_headers = dict(headers or {})
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")

    last_error = "unknown error"
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                payload = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            payload = exc.read()
            if expected_status is not None:
                allowed = expected_status if isinstance(expected_status, set) else {expected_status}
                if status in allowed:
                    return status, payload
            if attempt < RETRY_ATTEMPTS and should_retry_status(status):
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {label} after HTTP {status}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            last_error = f"HTTP {status}: {preview_body(payload)}"
            raise RuntimeError(f"{label} failed at {url}: {last_error}") from exc
        except urllib.error.URLError as exc:
            if attempt < RETRY_ATTEMPTS:
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {label} after network error",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise RuntimeError(f"{label} failed at {url}: {exc.reason}") from exc

        if expected_status is not None:
            allowed = expected_status if isinstance(expected_status, set) else {expected_status}
            if status not in allowed:
                raise RuntimeError(
                    f"{label} failed at {url}: expected {sorted(allowed)}, got HTTP {status}"
                )
        elif status >= 400:
            if attempt < RETRY_ATTEMPTS and should_retry_status(status):
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {label} after HTTP {status}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise RuntimeError(f"{label} failed at {url}: HTTP {status}")

        return status, payload

    raise RuntimeError(f"{label} failed at {url}: {last_error}")


def check(base_url: str, path: str) -> bool:
    url = f"{base_url}{path}"
    status, payload = request_with_retry(path, url)
    print(f"OK   {path}: HTTP {status} ({len(payload)} bytes)")
    return True


def check_cors(base_url: str, frontend_origin: str) -> bool:
    url = f"{base_url}/api/v1/summary"
    request = urllib.request.Request(url, method="GET", headers={"Origin": frontend_origin})

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = response.read()
                allowed_origin = response.headers.get("Access-Control-Allow-Origin")
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if attempt < RETRY_ATTEMPTS and should_retry_status(exc.code):
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for CORS after HTTP {exc.code}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise RuntimeError(
                f"CORS failed at {url}: HTTP {exc.code}: {preview_body(body)}"
            ) from exc
        except urllib.error.URLError as exc:
            if attempt < RETRY_ATTEMPTS:
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for CORS after network error",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise RuntimeError(f"CORS failed at {url}: {exc.reason}") from exc

        if allowed_origin != frontend_origin:
            raise RuntimeError(
                f"CORS failed at {url}: expected {frontend_origin}, got {allowed_origin or '(missing)'}"
            )

        print(f"OK   CORS: access-control-allow-origin={allowed_origin}")
        return True

    return False


def check_protected_routes(base_url: str, admin_api_key: str) -> bool:
    monitors_url = f"{base_url}/api/v1/monitors"
    status_page_url = f"{base_url}/api/v1/status-page"

    deny_status, _ = request_with_retry(
        "Protected monitors without auth",
        monitors_url,
        expected_status=PROTECTED_DENY_STATUSES,
    )
    print(f"OK   /api/v1/monitors without auth: HTTP {deny_status} (protected)")

    status_page_deny_status, _ = request_with_retry(
        "Protected status page without auth",
        status_page_url,
        expected_status=PROTECTED_DENY_STATUSES,
    )
    print(f"OK   /api/v1/status-page without auth: HTTP {status_page_deny_status} (protected)")

    auth_headers = {"Authorization": f"Bearer {admin_api_key}"}
    status, payload = request_with_retry(
        "Protected monitors with auth",
        monitors_url,
        headers=auth_headers,
        expected_status=200,
    )
    print(f"OK   /api/v1/monitors with auth: HTTP {status} ({len(payload)} bytes)")

    status_page_status, status_page_payload = request_with_retry(
        "Protected status page with auth",
        status_page_url,
        headers=auth_headers,
        expected_status=200,
    )
    print(
        f"OK   /api/v1/status-page with auth: HTTP {status_page_status} "
        f"({len(status_page_payload)} bytes)"
    )
    return True


def check_alert_settings_routes(base_url: str, admin_api_key: str) -> bool:
    alerts_url = f"{base_url}/api/v1/settings/alerts"

    deny_status, _ = request_with_retry(
        "Protected alert settings without auth",
        alerts_url,
        expected_status=PROTECTED_DENY_STATUSES,
    )
    print(f"OK   /api/v1/settings/alerts without auth: HTTP {deny_status} (protected)")

    auth_headers = {"Authorization": f"Bearer {admin_api_key}"}
    status, payload = request_with_retry(
        "Protected alert settings with auth",
        alerts_url,
        headers=auth_headers,
        expected_status=200,
    )
    print(f"OK   /api/v1/settings/alerts with auth: HTTP {status} ({len(payload)} bytes)")
    return True


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not backend_url:
        print("BACKEND_URL is required", file=sys.stderr)
        return 1

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/")
    admin_api_key = os.environ.get("ADMIN_API_KEY", "").strip()

    print(f"Checking backend at {backend_url}")
    try:
        results = [check(backend_url, path) for path in ENDPOINTS]

        if frontend_origin:
            print(f"Checking CORS for origin {frontend_origin}")
            results.append(check_cors(backend_url, frontend_origin))

        if admin_api_key:
            print("Checking protected monitor routes with ADMIN_API_KEY")
            results.append(check_protected_routes(backend_url, admin_api_key))
            results.append(check_alert_settings_routes(backend_url, admin_api_key))
    except RuntimeError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        print("Backend smoke test failed.", file=sys.stderr)
        return 1

    if all(results):
        print("Backend smoke test passed.")
        return 0

    print("Backend smoke test failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
