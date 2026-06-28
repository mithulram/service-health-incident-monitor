"""Email alert delivery and monitor transition handling."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Callable
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..config import Settings
from ..db import repositories as repo
from ..db.models import AlertSettings, CheckResult, Monitor, MonitorState
from .checks import CheckOutcome
from .state import STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN, STATUS_UP

LOGGER = logging.getLogger("service_monitor.alerts")

EVENT_OPENED = "opened"
EVENT_RESOLVED = "resolved"
EVENT_TEST = "test"

_smtp_sender: Callable[..., None] | None = None


@dataclass(frozen=True)
class EffectiveAlertConfig:
    enabled: bool
    send_resolved: bool
    smtp_host: str | None
    smtp_port: int
    smtp_username: str | None
    smtp_password: str | None
    smtp_from: str | None
    alert_to: str | None
    frontend_public_url: str | None

    @property
    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host
            and self.smtp_port
            and self.smtp_from
            and self.alert_to
            and self.smtp_password is not None
            and self.smtp_password != ""
        )

    @property
    def ready(self) -> bool:
        return self.enabled and self.smtp_configured


def set_smtp_sender_for_tests(sender: Callable[..., None] | None) -> None:
    global _smtp_sender
    _smtp_sender = sender


def ensure_default_alert_settings(session: Session) -> AlertSettings:
    return repo.ensure_alert_settings(session)


def build_effective_alert_config(settings: Settings, alert_settings: AlertSettings) -> EffectiveAlertConfig:
    env_enabled = settings.alerts_enabled
    db_enabled = alert_settings.enabled
    return EffectiveAlertConfig(
        enabled=db_enabled and env_enabled,
        send_resolved=alert_settings.send_resolved if alert_settings.send_resolved is not None else settings.alert_send_resolved,
        smtp_host=alert_settings.smtp_host or settings.smtp_host,
        smtp_port=alert_settings.smtp_port or settings.smtp_port,
        smtp_username=alert_settings.smtp_username or settings.smtp_username,
        smtp_password=settings.smtp_password,
        smtp_from=alert_settings.smtp_from or settings.smtp_from,
        alert_to=alert_settings.alert_to or settings.alert_email_to,
        frontend_public_url=settings.frontend_public_url,
    )


def build_alert_settings_response(settings: Settings, alert_settings: AlertSettings) -> dict[str, object]:
    effective = build_effective_alert_config(settings, alert_settings)
    return {
        "enabled": alert_settings.enabled,
        "send_resolved": alert_settings.send_resolved,
        "smtp_host": alert_settings.smtp_host or settings.smtp_host,
        "smtp_port": alert_settings.smtp_port or settings.smtp_port,
        "smtp_username": alert_settings.smtp_username or settings.smtp_username,
        "smtp_from": alert_settings.smtp_from or settings.smtp_from,
        "alert_to": alert_settings.alert_to or settings.alert_email_to,
        "smtp_password_configured": bool(settings.smtp_password),
        "smtp_configured": effective.smtp_configured,
        "alerts_ready": effective.ready,
        "env_alerts_enabled": settings.alerts_enabled,
        "created_at": alert_settings.created_at,
        "updated_at": alert_settings.updated_at,
    }


def _monitor_hostname(monitor: Monitor) -> str:
    parsed = urlparse(monitor.url)
    return parsed.hostname or monitor.name


def _format_checked_at(outcome: CheckOutcome | None) -> str:
    if outcome is None:
        return datetime.now(UTC).isoformat()
    checked_at = outcome.checked_at
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    return checked_at.astimezone(UTC).isoformat()


def _build_email_body(
    *,
    monitor: Monitor | None,
    outcome: CheckOutcome | None,
    event_type: str,
    frontend_public_url: str | None,
) -> tuple[str, str]:
    if event_type == EVENT_TEST:
        subject = "Service Health Monitor test alert"
        body = "This is a test alert from the Service Health & Incident Monitor."
        if frontend_public_url:
            body += f"\n\nDashboard: {frontend_public_url.rstrip('/')}"
        return subject, body

    assert monitor is not None
    hostname = _monitor_hostname(monitor)
    checked_at = _format_checked_at(outcome)

    if event_type == EVENT_OPENED:
        subject = f"[DOWN] {monitor.name}"
        lines = [
            f"Monitor: {monitor.name}",
            f"Target: {hostname}",
            f"Checked at: {checked_at}",
        ]
        if outcome and outcome.status_code is not None:
            lines.append(f"Status code: {outcome.status_code}")
        if outcome and outcome.error_message:
            lines.append(f"Error: {outcome.error_message}")
        lines.append("")
        lines.append("The monitor is currently failing checks.")
    else:
        subject = f"[RECOVERED] {monitor.name}"
        lines = [
            f"Monitor: {monitor.name}",
            f"Target: {hostname}",
            f"Checked at: {checked_at}",
            "",
            "The monitor is healthy again.",
        ]

    if frontend_public_url:
        lines.append(f"Status page: {frontend_public_url.rstrip('/')}/status/default")

    return subject, "\n".join(lines)


def _send_smtp_email(config: EffectiveAlertConfig, recipient: str, subject: str, body: str) -> None:
    if _smtp_sender is not None:
        _smtp_sender(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_username,
            password=config.smtp_password,
            sender=config.smtp_from,
            recipient=recipient,
            subject=subject,
            body=body,
        )
        return

    message = EmailMessage()
    message["From"] = config.smtp_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if config.smtp_username:
            smtp.login(config.smtp_username, config.smtp_password or "")
        smtp.send_message(message)


def send_alert_email(
    session: Session,
    settings: Settings,
    alert_settings: AlertSettings,
    *,
    event_type: str,
    monitor: Monitor | None = None,
    outcome: CheckOutcome | None = None,
    check_result: CheckResult | None = None,
) -> AlertEvent | None:
    config = build_effective_alert_config(settings, alert_settings)
    if not config.ready:
        return None

    recipient = config.alert_to
    if not recipient:
        return None

    subject, body = _build_email_body(
        monitor=monitor,
        outcome=outcome,
        event_type=event_type,
        frontend_public_url=config.frontend_public_url,
    )

    success = True
    error_message: str | None = None
    try:
        _send_smtp_email(config, recipient, subject, body)
    except Exception as exc:  # noqa: BLE001 - alert delivery must not break checks
        success = False
        error_message = str(exc)
        LOGGER.warning("Failed to send %s alert email: %s", event_type, exc)

    return repo.create_alert_event(
        session,
        monitor_id=monitor.id if monitor else None,
        check_result_id=check_result.id if check_result else None,
        event_type=event_type,
        recipient=recipient,
        subject=subject,
        success=success,
        error_message=error_message,
    )


def send_test_alert(session: Session, settings: Settings, alert_settings: AlertSettings) -> AlertEvent:
    config = build_effective_alert_config(settings, alert_settings)
    if not config.smtp_configured:
        raise ValueError("SMTP is not fully configured. Set SMTP env vars on the backend host.")
    if not config.alert_to:
        raise ValueError("Alert recipient is not configured.")

    event = send_alert_email(
        session,
        settings,
        alert_settings,
        event_type=EVENT_TEST,
    )
    if event is None:
        raise ValueError("Unable to send test alert.")
    return event


def _normalize_status(status: str | None) -> str:
    if status in {STATUS_UP, STATUS_DOWN, STATUS_PAUSED, STATUS_UNKNOWN}:
        return status
    return STATUS_UNKNOWN


def process_monitor_alert_transition(
    session: Session,
    monitor: Monitor,
    monitor_state: MonitorState,
    outcome: CheckOutcome,
    check_result: CheckResult,
    settings: Settings,
    *,
    previous_status: str | None,
) -> None:
    alert_settings = ensure_default_alert_settings(session)
    config = build_effective_alert_config(settings, alert_settings)
    if not config.ready:
        return

    old_status = _normalize_status(previous_status)
    new_status = _normalize_status(monitor_state.last_status)

    if new_status == STATUS_DOWN and old_status != STATUS_DOWN and not monitor_state.alert_open:
        send_alert_email(
            session,
            settings,
            alert_settings,
            event_type=EVENT_OPENED,
            monitor=monitor,
            outcome=outcome,
            check_result=check_result,
        )
        monitor_state.alert_open = True
        monitor_state.alert_opened_at = datetime.now(UTC)
        session.flush()

    elif (
        new_status == STATUS_UP
        and old_status == STATUS_DOWN
        and monitor_state.alert_open
        and config.send_resolved
    ):
        send_alert_email(
            session,
            settings,
            alert_settings,
            event_type=EVENT_RESOLVED,
            monitor=monitor,
            outcome=outcome,
            check_result=check_result,
        )
        monitor_state.alert_open = False
        monitor_state.alert_opened_at = None
        session.flush()
