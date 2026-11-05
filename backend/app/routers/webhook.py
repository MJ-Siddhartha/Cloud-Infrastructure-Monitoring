"""Alertmanager webhook receiver endpoint."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.schemas.webhook import AlertmanagerWebhook
from app.services import incident_service
from app.services.notification_service import (
    send_email_notification,
    send_telegram_notification,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _parse_starts_at(value: str) -> datetime:
    """Parse the startsAt timestamp from Alertmanager."""
    if not value:
        return datetime.now(timezone.utc)
    try:
        # Handle Alertmanager's ISO-8601 format
        cleaned = value.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


@router.post("/alertmanager")
async def receive_alertmanager_webhook(
    payload: AlertmanagerWebhook,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Receive and process an Alertmanager webhook payload."""
    processed = 0
    logger.info(
        "Received Alertmanager webhook: status=%s alerts=%d receiver=%s",
        payload.status,
        len(payload.alerts),
        payload.receiver,
    )

    for alert in payload.alerts:
        try:
            fingerprint = alert.fingerprint
            alert_name = alert.labels.alertname
            severity = alert.labels.severity
            instance = alert.labels.instance
            description = alert.annotations.description or alert.annotations.summary

            # Extract metric info from extra labels
            extra_labels = alert.labels.model_extra or {}
            metric_name = extra_labels.get("metric_name")
            metric_value = extra_labels.get("metric_value")

            alert_data = {
                "fingerprint": fingerprint,
                "alert_name": alert_name,
                "severity": severity,
                "instance": instance,
                "description": description,
                "metric_name": metric_name,
                "metric_value": metric_value,
                "started_at": _parse_starts_at(alert.startsAt),
                "webhook_payload": payload.model_dump(),
            }

            if alert.status == "firing":
                # De-duplicate: skip if already firing with same fingerprint
                existing = await incident_service.find_firing_incident(db, fingerprint)
                if existing:
                    logger.info(
                        "Duplicate firing alert for fingerprint=%s, skipping",
                        fingerprint,
                    )
                    continue

                incident = await incident_service.create_incident(db, alert_data)
                logger.info("Created incident id=%s for alert=%s", incident.id, alert_name)

                # Send notifications (fire-and-forget)
                asyncio.create_task(send_telegram_notification(alert_data))
                asyncio.create_task(send_email_notification(alert_data))

                # Recovery (if enabled)
                settings = get_settings()
                if settings.RECOVERY_ENABLED:
                    try:
                        from app.recovery.engine import RecoveryEngine, ALERT_PLAYBOOK_MAP

                        if alert_name in ALERT_PLAYBOOK_MAP:
                            engine = RecoveryEngine(settings)
                            if engine.should_recover(alert_name, instance, fingerprint):
                                labels_dict = alert.labels.model_dump()
                                asyncio.create_task(
                                    engine.execute_recovery(
                                        incident.id,
                                        alert_name,
                                        instance,
                                        labels_dict,
                                        db,
                                    )
                                )
                    except Exception as exc:
                        logger.error("Recovery trigger failed: %s", exc)

                processed += 1

            elif alert.status == "resolved":
                resolved_at = datetime.now(timezone.utc)
                if alert.endsAt:
                    resolved_at = _parse_starts_at(alert.endsAt)

                incident = await incident_service.resolve_incident(db, fingerprint, resolved_at)
                if incident:
                    logger.info("Resolved incident id=%s", incident.id)
                    processed += 1
                else:
                    logger.warning(
                        "No firing incident found for resolved fingerprint=%s",
                        fingerprint,
                    )
            else:
                logger.warning("Unknown alert status: %s", alert.status)

        except Exception as exc:
            logger.error("Error processing alert: %s", exc)
            raise HTTPException(status_code=500, detail=f"Error processing alert: {exc}")

    return {"status": "accepted", "processed": processed}
