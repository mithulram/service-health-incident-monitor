"""Shared helpers for backend unit tests."""

from __future__ import annotations

import os
import subprocess
import unittest

DEFAULT_TEST_DATABASE_URL = "sqlite:///:memory:"


def test_database_url() -> str:
    value = os.environ.get("DATABASE_URL", DEFAULT_TEST_DATABASE_URL).strip()
    return value or DEFAULT_TEST_DATABASE_URL


def uses_postgres() -> bool:
    return test_database_url().startswith("postgresql")


def reset_test_database() -> None:
    """Reset persisted rows between tests when running against shared Postgres."""
    if not uses_postgres():
        return

    from service_monitor.db.engine import dispose_engine

    dispose_engine()
    env = os.environ.copy()
    subprocess.check_call(["alembic", "downgrade", "base"], env=env)
    subprocess.check_call(["alembic", "upgrade", "head"], env=env)


def install_postgres_test_isolation() -> None:
    if not uses_postgres() or getattr(unittest.TestCase, "_postgres_isolation_installed", False):
        return

    original_setUp = unittest.TestCase.setUp

    def setUp(self) -> None:
        reset_test_database()
        original_setUp(self)

    unittest.TestCase.setUp = setUp
    unittest.TestCase._postgres_isolation_installed = True  # type: ignore[attr-defined]


install_postgres_test_isolation()
