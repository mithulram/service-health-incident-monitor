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
    "/api/v1/summary",
    "/api/v1/incidents",
    "/metrics",
)
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
RETRYABLE_STATUS_CODES = {429, 502, 503, 504}


def preview_body(body: bytes, max_length: int = 120) -> str:
    text = " ".join(body.decode("utf-8", errors="replace").split())
    if not text:
        return "(empty body)"
    if len(text) <= max_length:
        return text
    return f"{text[:max_length]}..."


def should_retry_status(status: int) -> bool:
    return status in RETRYABLE_STATUS_CODES


def check(base_url: str, path: str) -> bool:
    url = f"{base_url}{path}"

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if attempt < RETRY_ATTEMPTS and should_retry_status(exc.code):
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {path} after HTTP {exc.code}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print(f"FAIL {path}", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"HTTP {exc.code}", file=sys.stderr)
            print(f"Preview: {preview_body(body)}", file=sys.stderr)
            return False
        except urllib.error.URLError as exc:
            if attempt < RETRY_ATTEMPTS:
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {path} after network error",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print(f"FAIL {path}", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"Error: {exc.reason}", file=sys.stderr)
            return False

        if status >= 400:
            if attempt < RETRY_ATTEMPTS and should_retry_status(status):
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for {path} after HTTP {status}",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print(f"FAIL {path}", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"HTTP {status}", file=sys.stderr)
            print(f"Preview: {preview_body(body)}", file=sys.stderr)
            return False

        print(f"OK   {path}: HTTP {status} ({len(body)} bytes)")
        return True

    return False


def check_cors(base_url: str, frontend_origin: str) -> bool:
    url = f"{base_url}/api/v1/summary"

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"Origin": frontend_origin},
        )
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
            print("FAIL CORS", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"HTTP {exc.code}", file=sys.stderr)
            print(f"Preview: {preview_body(body)}", file=sys.stderr)
            return False
        except urllib.error.URLError as exc:
            if attempt < RETRY_ATTEMPTS:
                print(
                    f"Retry {attempt}/{RETRY_ATTEMPTS - 1} for CORS after network error",
                    file=sys.stderr,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            print("FAIL CORS", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"Error: {exc.reason}", file=sys.stderr)
            return False

        if allowed_origin != frontend_origin:
            print("FAIL CORS", file=sys.stderr)
            print(f"URL: {url}", file=sys.stderr)
            print(f"HTTP {status}", file=sys.stderr)
            print(f"Expected access-control-allow-origin: {frontend_origin}", file=sys.stderr)
            print(f"Got: {allowed_origin or '(missing)'}", file=sys.stderr)
            print(f"Preview: {preview_body(body)}", file=sys.stderr)
            return False

        print(f"OK   CORS: access-control-allow-origin={allowed_origin}")
        return True

    return False


def main() -> int:
    backend_url = os.environ.get("BACKEND_URL", "").strip().rstrip("/")
    if not backend_url:
        print("BACKEND_URL is required", file=sys.stderr)
        return 1

    frontend_origin = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/")

    print(f"Checking backend at {backend_url}")
    results = [check(backend_url, path) for path in ENDPOINTS]

    if frontend_origin:
        print(f"Checking CORS for origin {frontend_origin}")
        results.append(check_cors(backend_url, frontend_origin))

    if all(results):
        print("Backend smoke test passed.")
        return 0

    print("Backend smoke test failed.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
