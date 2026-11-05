"""Notification services for Telegram and Email alerts."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
try:
    import aiosmtplib
except ImportError:
    aiosmtplib = None
from email.mime.text import MIMEText

from app.config import get_settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _format_alert_message(alert_data: dict) -> str:
    """Build a human-readable alert message."""
    alert_name = alert_data.get('alert_name', 'Unknown')
    severity = alert_data.get('severity', 'unknown').upper()
    icon = "🔴" if severity == "CRITICAL" else "🟡"
    lines = [
        f"{icon} <b>ALERT: {alert_name}</b>",
        f"<b>Severity:</b> {severity}",
        f"<b>Instance:</b> {alert_data.get('instance', 'N/A')}",
        f"<b>Description:</b> {alert_data.get('description', 'N/A')}",
        f"<b>Metric Value:</b> {alert_data.get('metric_value', 'N/A')}",
        f"<b>Timestamp:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
    ]
    return "\n".join(lines)


async def send_telegram_notification(alert_data: dict) -> None:
    """Send an alert notification via Telegram Bot API."""
    settings = get_settings()
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured in settings, skipping notification")
        return

    message = _format_alert_message(alert_data)
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
            if response.status_code != 200:
                logger.error("Telegram API responded with error %s: %s", response.status_code, response.text)
                # Retry with plain text without formatting
                payload.pop("parse_mode", None)
                await client.post(url, json=payload)
            else:
                logger.info("Telegram notification sent for alert=%s", alert_data.get("alert_name"))
    except httpx.HTTPError as exc:
        logger.error("Failed to send Telegram notification: %s", exc)
    except Exception as exc:
        logger.error("Unexpected error sending Telegram notification: %s", exc)


async def send_email_notification(alert_data: dict) -> None:
    """Send an alert notification via SMTP email."""
    settings = get_settings()
    if aiosmtplib is None:
        logger.warning("aiosmtplib is not installed; skipping email notification")
        return
    if not settings.SMTP_TO_EMAIL:
        logger.debug("SMTP_TO_EMAIL not configured, skipping email notification")
        return

    message_text = _format_alert_message(alert_data)
    msg = MIMEText(message_text, "plain")
    msg["Subject"] = f"[ALERT] {alert_data.get('alert_name', 'Unknown')} - {alert_data.get('severity', 'unknown')}"
    msg["From"] = settings.SMTP_FROM_EMAIL
    msg["To"] = settings.SMTP_TO_EMAIL

    try:
        smtp_kwargs: dict = {
            "hostname": settings.SMTP_HOST,
            "port": settings.SMTP_PORT,
        }
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            smtp_kwargs["username"] = settings.SMTP_USERNAME
            smtp_kwargs["password"] = settings.SMTP_PASSWORD
            smtp_kwargs["use_tls"] = True

        await aiosmtplib.send(msg, **smtp_kwargs)
        logger.info("Email notification sent for alert=%s", alert_data.get("alert_name"))
    except aiosmtplib.SMTPException as exc:
        logger.error("Failed to send email notification: %s", exc)
    except Exception as exc:
        logger.error("Unexpected error sending email notification: %s", exc)
