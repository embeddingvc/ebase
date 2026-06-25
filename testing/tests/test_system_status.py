"""Tests for cron.system_status."""

from __future__ import annotations

from cron import system_status as ss


def test_probe_browser_unreachable() -> None:
    browser = ss.probe_browser()
    assert "reachable" in browser
    assert "managed" in browser
    assert "restart_hint" in browser


def test_format_browser_lines() -> None:
    lines = ss.format_browser_lines()
    assert any("Chrome CDP" in line for line in lines)
