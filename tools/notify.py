"""
Operator notifications for outreach events.

The SMTP sink backs two notifications:

* ``send_meeting_scheduled_email`` — fires from the live ``schedule_meeting``
  MCP tool when a prospect agrees to a call.
* ``send_conversation_ended_email`` — fires from the live
  ``upsert_conversation`` MCP tool when a sequence transitions into a terminal
  stage (``ended`` / ``dead``).

Both functions share the same env-var configuration and the same
``"sent" | "skipped" | "error: ..."`` contract. They are no-ops when
``OPERATOR_EMAIL`` or ``SMTP_HOST`` is unset, so the same call sites are safe
in dev, in tests, and when a user simply hasn't configured email yet.

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


def _resolve_smtp_config(prospect_id: str, *, label: str) -> dict | None:
    """Read SMTP settings from env. Returns None if sending is disabled/unconfigured."""
    if notifications_disabled():
        logger.info(
            "notify: NOTIFY_DISABLED set; skipping %s email for %s", label, prospect_id
        )
        return None

    operator_email = (os.environ.get("OPERATOR_EMAIL") or "").strip()
    smtp_host = (os.environ.get("SMTP_HOST") or "").strip()
    if not operator_email or not smtp_host:
        logger.info(
            "notify: SMTP not configured (OPERATOR_EMAIL=%s SMTP_HOST=%s); skipping %s email for %s",
            bool(operator_email),
            bool(smtp_host),
            label,
            prospect_id,
        )
        return None

    smtp_user = (os.environ.get("SMTP_USER") or "").strip()
    smtp_pass = os.environ.get("SMTP_PASS") or ""
    sender = (os.environ.get("SMTP_FROM") or "").strip() or smtp_user or operator_email
    return {
        "operator_email": operator_email,
        "smtp_host": smtp_host,
        "smtp_user": smtp_user,
        "smtp_pass": smtp_pass,
        "sender": sender,
        "port": _smtp_port(),
        "timeout": _smtp_timeout(),
        "use_starttls": _starttls_enabled(),
    }


def _dispatch(
    msg: EmailMessage,
    cfg: dict,
    *,
    prospect_id: str,
    label: str,
) -> str:
    """Send ``msg`` over SMTP using ``cfg``. Returns the 'sent' / 'error: ...' string."""
    try:
        with smtplib.SMTP(
            cfg["smtp_host"], cfg["port"], timeout=cfg["timeout"]
        ) as client:
            client.ehlo()
            if cfg["use_starttls"]:
                client.starttls()
                client.ehlo()
            if cfg["smtp_user"]:
                client.login(cfg["smtp_user"], cfg["smtp_pass"])
            client.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.warning(
            "notify: SMTP send failed label=%s prospect_id=%s host=%s port=%s error=%s",
            label,
            prospect_id,
            cfg["smtp_host"],
            cfg["port"],
            exc,
        )
        return f"error: {exc}"

    logger.info(
        "notify: %s email sent prospect_id=%s to=%s",
        label,
        prospect_id,
        cfg["operator_email"],
    )
    return "sent"


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

    link_line = (
        meeting_link.strip() if meeting_link else "(book the calendar invite manually)"
    )
    body = (
        f"A LinkedIn outreach meeting was just scheduled.\n"
        f"\n"
        f"Prospect:   {display_name}\n"
        f"Profile:    {profile_url or '(unknown)'}\n"
        f"Email:      {email}\n"
        f"When (UTC): {scheduled_at}\n"
        f"Meeting:    {link_line}\n"
        f"\n"
        f"Scheduled via ebase.\n"
    )
    msg.set_content(body)
    return msg


def _build_ended_email(
    *,
    prospect_name: str,
    profile_url: str,
    outreach_stage: str,
    ended_reason: str,
    ended_at: str,
    sequence_step: int | None,
    report_path: str | None,
    end_goal: str | None,
    sender: str,
    recipient: str,
) -> EmailMessage:
    msg = EmailMessage()
    display_name = (prospect_name or "Unknown prospect").strip() or "Unknown prospect"
    verb = "closed" if outreach_stage == "ended" else "dropped"
    reason_tag = (ended_reason or "no_reason").strip() or "no_reason"
    msg["Subject"] = f"LinkedIn outreach {verb} — {display_name} ({reason_tag})"
    msg["From"] = sender
    msg["To"] = recipient

    step_line = str(sequence_step) if isinstance(sequence_step, int) else "(none)"
    body = (
        f"A LinkedIn outreach sequence just reached a terminal state.\n"
        f"\n"
        f"Prospect:    {display_name}\n"
        f"Profile:     {profile_url or '(unknown)'}\n"
        f"Stage:       {outreach_stage}\n"
        f"Reason:      {reason_tag}\n"
        f"Ended (UTC): {ended_at or '(unknown)'}\n"
        f"End goal:    {end_goal or '(unspecified)'}\n"
        f"Last step:   {step_line}\n"
        f"Report:      {report_path or '(no report written)'}\n"
        f"\n"
        f"Closed via ebase.\n"
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
    cfg = _resolve_smtp_config(prospect_id, label="meeting")
    if cfg is None:
        return "skipped"

    msg = _build_meeting_email(
        prospect_name=prospect_name,
        profile_url=profile_url,
        email=email,
        scheduled_at=scheduled_at,
        meeting_link=meeting_link,
        sender=cfg["sender"],
        recipient=cfg["operator_email"],
    )
    return _dispatch(msg, cfg, prospect_id=prospect_id, label="meeting")


def send_conversation_ended_email(
    *,
    prospect_id: str,
    prospect_name: str,
    profile_url: str,
    outreach_stage: str,
    ended_reason: str,
    ended_at: str,
    sequence_step: int | None = None,
    report_path: str | None = None,
    end_goal: str | None = None,
) -> str:
    """
    Email the operator that a LinkedIn outreach sequence just ended.

    Fires from ``upsert_conversation`` when a thread transitions into a terminal
    ``outreach_stage`` (``ended`` or ``dead``). Same ``"sent" | "skipped" |
    "error: ..."`` contract as :func:`send_meeting_scheduled_email`; the caller
    should never roll back the conversation write on an ``error: ...`` result.
    """
    cfg = _resolve_smtp_config(prospect_id, label="ended")
    if cfg is None:
        return "skipped"

    msg = _build_ended_email(
        prospect_name=prospect_name,
        profile_url=profile_url,
        outreach_stage=outreach_stage,
        ended_reason=ended_reason,
        ended_at=ended_at,
        sequence_step=sequence_step,
        report_path=report_path,
        end_goal=end_goal,
        sender=cfg["sender"],
        recipient=cfg["operator_email"],
    )
    return _dispatch(msg, cfg, prospect_id=prospect_id, label="ended")
