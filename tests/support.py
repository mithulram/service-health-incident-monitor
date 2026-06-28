"""Shared helpers for backend unit tests."""

from __future__ import annotations

import os
import subprocess
import unittest

DEFAULT_TEST_DATABASE_URL = "sqlite:///:memory:"


def test_database_url() -> str:
    pg_host = os.environ.get("PGHOST", "").strip()
    if pg_host:
        pg_port = os.environ.get("PGPORT", "5432").strip()
        pg_user = os.environ.get("PGUSER", "").strip()
        pg_password = os.environ.get("PGPASSWORD", "").strip()
        pg_database = os.environ.get("PGDATABASE", "").strip()
        if pg_user and pg_password and pg_database:
            return (
                f"postgresql+psycopg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_database}"
            )

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
    env["DATABASE_URL"] = test_database_url()
    subprocess.check_call(["alembic", "downgrade", "base"], env=env)
    subprocess.check_call(["alembic", "upgrade", "head"], env=env)


def install_postgres_test_isolation() -> None:
    if not uses_postgres() or getattr(unittest.TestCase, "_postgres_isolation_installed", False):
        return

    original_run = unittest.TestCase.run

    def run(self, result=None):
        reset_test_database()
        return original_run(self, result)

    unittest.TestCase.run = run  # type: ignore[method-assign]
    unittest.TestCase._postgres_isolation_installed = True  # type: ignore[attr-defined]


install_postgres_test_isolation()
