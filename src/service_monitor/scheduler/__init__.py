"""Background scheduler for automatic monitor checks."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import Settings
from ..db.engine import session_scope
from ..db import repositories as repo
from ..db.models import Monitor
from ..services.check_runner import execute_monitor_check

LOGGER = logging.getLogger("service_monitor.scheduler")


def _run_scheduled_check(monitor_id: int, settings: Settings) -> None:
    try:
        with session_scope() as session:
            execute_monitor_check(session, monitor_id, settings)
    except LookupError:
        LOGGER.warning("scheduled_check_skipped monitor_id=%s reason=not_found", monitor_id)
    except Exception:
        LOGGER.exception("scheduled_check_failed monitor_id=%s", monitor_id)


class MonitorScheduler:
    """Single-instance interval scheduler for non-paused monitors."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._scheduler = BackgroundScheduler(timezone="UTC")
        self._started = False

    @property
    def enabled(self) -> bool:
        return self._settings.scheduler_enabled

    def start(self) -> None:
        if not self.enabled or self._started:
            return
        with session_scope() as session:
            for monitor in repo.list_active_monitors(session):
                self._schedule_monitor(monitor)
        self._scheduler.start()
        self._started = True
        LOGGER.info("monitor_scheduler_started")

    def shutdown(self) -> None:
        if not self._started:
            return
        self._scheduler.shutdown(wait=False)
        self._started = False
        LOGGER.info("monitor_scheduler_stopped")

    def _job_id(self, monitor_id: int) -> str:
        return f"monitor-check-{monitor_id}"

    def _schedule_monitor(self, monitor: Monitor) -> None:
        if monitor.is_paused:
            self.unschedule_monitor(monitor.id)
            return
        self._scheduler.add_job(
            _run_scheduled_check,
            trigger=IntervalTrigger(seconds=monitor.interval_seconds),
            id=self._job_id(monitor.id),
            replace_existing=True,
            kwargs={"monitor_id": monitor.id, "settings": self._settings},
            max_instances=1,
            coalesce=True,
        )

    def unschedule_monitor(self, monitor_id: int) -> None:
        job_id = self._job_id(monitor_id)
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    def sync_monitor(self, monitor: Monitor) -> None:
        if not self.enabled or not self._started:
            return
        if monitor.is_paused:
            self.unschedule_monitor(monitor.id)
        else:
            self._schedule_monitor(monitor)

    def remove_monitor(self, monitor_id: int) -> None:
        if not self._started:
            return
        self.unschedule_monitor(monitor_id)
