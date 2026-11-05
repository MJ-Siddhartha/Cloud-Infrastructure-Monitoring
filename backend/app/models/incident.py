"""Incident SQLAlchemy model."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)

from app.database import Base


class Incident(Base):
    """Represents a monitoring incident created from an alert."""

    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fingerprint = Column(String(64), nullable=False, index=True)
    alert_name = Column(String(255), nullable=False)
    severity = Column(String(50), default="warning")
    instance = Column(String(255), nullable=True)
    metric_name = Column(String(255), nullable=True)
    metric_value = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="firing", index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    webhook_payload = Column(JSON, nullable=True)
    recovery_action = Column(String(255), nullable=True)
    recovery_status = Column(String(50), nullable=True)
    recovery_started_at = Column(DateTime(timezone=True), nullable=True)
    recovery_completed_at = Column(DateTime(timezone=True), nullable=True)
    recovery_output = Column(Text, nullable=True)
    recovery_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("fingerprint", "started_at", name="uq_fingerprint_started_at"),
        Index("ix_incidents_alert_name", "alert_name"),
        Index("ix_incidents_instance", "instance"),
        Index("ix_incidents_severity", "severity"),
    )

    def __repr__(self) -> str:
        return f"<Incident(id={self.id}, alert_name='{self.alert_name}', status='{self.status}')>"
