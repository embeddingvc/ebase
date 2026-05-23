"""
Operator notifications for outreach events.

v1 ships a single SMTP sink so the live ``schedule_meeting`` MCP tool can drop
a plain-text reminder into the operator's inbox. The function is a no-op when
``OPERATOR_EMAIL`` or ``SMTP_HOST`` is unset, so the same call site is safe in
dev, in tests, and when a user simply hasn't configured email yet.

Environment variables (read on every send so ``.env`` edits apply without a
server restart):

================  ===================================================
``OPERATOR_EMAIL``  Recipient. Empty disables sending.
``SMTP_HOST``       SMTP server hostname. Empty disables sending.
``SMTP_PORT``       Defaults to ``587``.
``SMTP_USER``       Auth username. Empty skips ``login()``.
``SMTP_PASS``       Auth password (Gmail: use an app password).
``SMTP_FROM``       From header. Falls back to ``SMTP_USER`` then ``OPERATOR_EMAIL``.
``SMTP_STARTTLS``   ``1`` (default) wraps the session in STARTTLS.
``SMTP_TIMEOUT_SEC`` Socket timeout in seconds (default ``8``).
``NOTIFY_DISABLED`` ``1`` / ``true`` / ``yes`` short-circuits all sends.
================  ===================================================
"""

from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger("linkedin.notify")

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def notifications_disabled() -> bool:
    flag = os.environ.get("NOTIFY_DISABLED", "").strip().lower()
    return flag in _TRUTHY


def _starttls_enabled() -> bool:
    raw = os.environ.get("SMTP_STARTTLS", "").strip().lower()
    if not raw:
        return True
    return raw in _TRUTHY


def _smtp_timeout() -> float:
    raw = os.environ.get("SMTP_TIMEOUT_SEC", "").strip()
    if not raw:
        return 8.0
    try:
        return max(1.0, float(raw))
    except ValueError:
        logger.warning("invalid SMTP_TIMEOUT_SEC=%r; using 8s", raw)
        return 8.0


def _smtp_port() -> int:
    raw = os.environ.get("SMTP_PORT", "").strip()
    if not raw:
        return 587
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid SMTP_PORT=%r; using 587", raw)
        return 587


def _build_meeting_email(
    *,
    prospect_name: str,
    profile_url: str,
    email: str,
    scheduled_at: str,
    meeting_link: str,
    sender: str,
    recipient: str,
) -> EmailMessage:
    msg = EmailMessage()
    display_name = (prospect_name or "Unknown prospect").strip() or "Unknown prospect"
    msg["Subject"] = f"LinkedIn meeting scheduled — {display_name} @ {scheduled_at}"
    msg["From"] = sender
    msg["To"] = recipient

    link_line = meeting_link.strip() if meeting_link else "(book the calendar invite manually)"
    body = (
        f"A LinkedIn outreach meeting was just scheduled.\n"
        f"\n"
        f"Prospect:   {display_name}\n"
        f"Profile:    {profile_url or '(unknown)'}\n"
        f"Email:      {email}\n"
        f"When (UTC): {scheduled_at}\n"
        f"Meeting:    {link_line}\n"
        f"\n"
        f"Scheduled via LinkedIn-Outreach.\n"
    )
    msg.set_content(body)
    return msg


def send_meeting_scheduled_email(
    *,
    prospect_id: str,
    prospect_name: str,
    profile_url: str,
    email: str,
    scheduled_at: str,
    meeting_link: str,
) -> str:
    """
    Email the operator that a meeting was just scheduled.

    Returns one of:

    - ``"sent"`` — message handed off to the SMTP server.
    - ``"skipped"`` — notifications disabled or SMTP not configured (not an error;
      the caller should treat the tool call as a success).
    - ``"error: <detail>"`` — SMTP raised an exception; the caller should log it
      but should **not** roll back the conversation write.
    """
    if notifications_disabled():
        logger.info("notify: NOTIFY_DISABLED set; skipping email for %s", prospect_id)
        return "skipped"

    operator_email = (os.environ.get("OPERATOR_EMAIL") or "").strip()
    smtp_host = (os.environ.get("SMTP_HOST") or "").strip()
    if not operator_email or not smtp_host:
        logger.info(
            "notify: SMTP not configured (OPERATOR_EMAIL=%s SMTP_HOST=%s); skipping email for %s",
            bool(operator_email),
            bool(smtp_host),
            prospect_id,
        )
        return "skipped"

    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_pass = os.environ.get("SMTP_PASS") or ""
    sender = (
        (os.environ.get("SMTP_FROM") or "").strip()
        or smtp_user
        or operator_email
    )
    port = _smtp_port()
    timeout = _smtp_timeout()
    use_starttls = _starttls_enabled()

    msg = _build_meeting_email(
        prospect_name=prospect_name,
        profile_url=profile_url,
        email=email,
        scheduled_at=scheduled_at,
        meeting_link=meeting_link,
        sender=sender,
        recipient=operator_email,
    )

    try:
        with smtplib.SMTP(smtp_host, port, timeout=timeout) as client:
            client.ehlo()
            if use_starttls:
                client.starttls()
                client.ehlo()
            if smtp_user:
                client.login(smtp_user, smtp_pass)
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "notify: SMTP send failed prospect_id=%s host=%s port=%s error=%s",
            prospect_id,
            smtp_host,
            port,
            exc,
        )
        return f"error: {exc}"

    logger.info(
        "notify: meeting email sent prospect_id=%s to=%s scheduled_at=%s",
        prospect_id,
        operator_email,
        scheduled_at,
    )
    return "sent"
