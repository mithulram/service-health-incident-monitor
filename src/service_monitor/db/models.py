"""SQLAlchemy ORM models for persisted monitors."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Monitor(Base):
    __tablename__ = "monitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False, default="GET")
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    expected_status_min: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    expected_status_max: Mapped[int] = mapped_column(Integer, nullable=False, default=399)
    is_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    check_results: Mapped[list[CheckResult]] = relationship(
        "CheckResult",
        back_populates="monitor",
        cascade="all, delete-orphan",
    )
    monitor_state: Mapped[MonitorState | None] = relationship(
        "MonitorState",
        back_populates="monitor",
        cascade="all, delete-orphan",
        uselist=False,
    )


class MonitorState(Base):
    __tablename__ = "monitor_states"

    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"),
        primary_key=True,
    )
    last_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uptime_ratio_24h: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_ratio_7d: Mapped[float | None] = mapped_column(Float, nullable=True)
    alert_open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    alert_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="monitor_state")


class CheckResult(Base):
    __tablename__ = "check_results"
    __table_args__ = (
        Index("ix_check_results_monitor_id_checked_at", "monitor_id", "checked_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int] = mapped_column(ForeignKey("monitors.id", ondelete="CASCADE"), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    monitor: Mapped[Monitor] = relationship("Monitor", back_populates="check_results")


class StatusPage(Base):
    __tablename__ = "status_pages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_response_times: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    components: Mapped[list[StatusPageComponent]] = relationship(
        "StatusPageComponent",
        back_populates="status_page",
        cascade="all, delete-orphan",
        order_by="StatusPageComponent.sort_order",
    )


class StatusPageComponent(Base):
    __tablename__ = "status_page_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status_page_id: Mapped[int] = mapped_column(
        ForeignKey("status_pages.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status_page: Mapped[StatusPage] = relationship("StatusPage", back_populates="components")
    monitor_links: Mapped[list[StatusPageComponentMonitor]] = relationship(
        "StatusPageComponentMonitor",
        back_populates="component",
        cascade="all, delete-orphan",
    )


class StatusPageComponentMonitor(Base):
    __tablename__ = "status_page_component_monitors"
    __table_args__ = (
        Index(
            "uq_status_page_component_monitors_component_monitor",
            "component_id",
            "monitor_id",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    component_id: Mapped[int] = mapped_column(
        ForeignKey("status_page_components.id", ondelete="CASCADE"),
        nullable=False,
    )
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey("monitors.id", ondelete="CASCADE"),
        nullable=False,
    )

    component: Mapped[StatusPageComponent] = relationship(
        "StatusPageComponent",
        back_populates="monitor_links",
    )
    monitor: Mapped[Monitor] = relationship("Monitor")


class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password_encrypted_or_secret_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_from: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alert_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    send_resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"
    __table_args__ = (Index("ix_alert_events_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int | None] = mapped_column(ForeignKey("monitors.id", ondelete="SET NULL"), nullable=True)
    check_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("check_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_started_at", "started_at"),
        Index("ix_incidents_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monitor_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitors.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="major")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    monitor: Mapped[Monitor | None] = relationship("Monitor")
    updates: Mapped[list[IncidentUpdate]] = relationship(
        "IncidentUpdate",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentUpdate.created_at",
    )


class IncidentUpdate(Base):
    __tablename__ = "incident_updates"
    __table_args__ = (
        Index("ix_incident_updates_incident_id_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    incident: Mapped[Incident] = relationship("Incident", back_populates="updates")
