"""Pydantic schemas for Alertmanager webhook payloads."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AlertLabel(BaseModel):
    """Labels attached to an alert."""

    model_config = ConfigDict(extra="allow")

    alertname: str
    severity: str = "warning"
    instance: str = ""
    job: str = ""


class AlertAnnotation(BaseModel):
    """Annotations attached to an alert."""

    model_config = ConfigDict(extra="allow")

    summary: str = ""
    description: str = ""


class Alert(BaseModel):
    """A single alert from Alertmanager."""

    model_config = ConfigDict(extra="allow")

    status: str  # firing | resolved
    labels: AlertLabel
    annotations: AlertAnnotation = AlertAnnotation()
    startsAt: str = ""
    endsAt: str = ""
    generatorURL: str | None = None
    fingerprint: str = ""


class AlertmanagerWebhook(BaseModel):
    """Full Alertmanager webhook payload."""

    model_config = ConfigDict(extra="allow")

    version: str = "4"
    groupKey: str = ""
    status: str = ""
    receiver: str = ""
    alerts: list[Alert] = []
    groupLabels: dict = {}
    commonLabels: dict = {}
    commonAnnotations: dict = {}
    externalURL: str | None = None
