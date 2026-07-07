"""Tests for cron.system_status."""

from __future__ import annotations

import logging

import pytest

from cron import system_status as ss


def test_probe_browser_unreachable() -> None:
    browser = ss.probe_browser()
    assert "reachable" in browser
    assert "managed" in browser
    assert "starts_on_demand" in browser


def test_format_browser_lines() -> None:
    lines = ss.format_browser_lines()
    assert any("Chrome CDP" in line for line in lines)


def test_check_services_returns_both_probes() -> None:
    result = ss.check_services()
    assert "browser" in result and "cron_server" in result
    assert "reachable" in result["browser"]
    assert "reachable" in result["cron_server"]


def test_check_services_logs_warning_for_unreachable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Chrome boots on demand now, so being down is expected and shouldn't warn —
    # only the cron server's health is worth a startup warning here.
    with caplog.at_level(logging.WARNING):
        result = ss.check_services()
    assert not any(
        record.levelno == logging.WARNING and "browser" in record.getMessage().lower()
        for record in caplog.records
    )
    if not result["cron_server"].get("running"):
        assert any(
            record.levelno == logging.WARNING and "cron server" in record.getMessage().lower()
            for record in caplog.records
        ), "expected a warning logged for unreachable cron server"
