"""
Combined Chrome + cron status for ``make status`` and tooling.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from cron.status_report import build_cron_status, format_sweep_lines

_BROWSER_LAUNCHD_LABEL = "com.embeddingvc.ebase.browser"
_BROWSER_SYSTEMD_UNIT = "ebase-browser.service"


def _browser_service_managed() -> tuple[bool, str | None, Path | None]:
    home = Path.home()
    system = platform.system()
    if system == "Darwin":
        path = home / "Library/LaunchAgents" / f"{_BROWSER_LAUNCHD_LABEL}.plist"
        return path.is_file(), "launchd" if path.is_file() else None, path if path.is_file() else None
    if system == "Linux":
        path = home / ".config/systemd/user" / _BROWSER_SYSTEMD_UNIT
        return path.is_file(), "systemd" if path.is_file() else None, path if path.is_file() else None
    return False, None, None


def _cdp_port() -> str:
    return os.environ.get("CDP_PORT", "9222")


def _cdp_url() -> str:
    return f"http://127.0.0.1:{_cdp_port()}/json/version"


def _chrome_profile() -> str:
    return os.environ.get("CHROME_PROFILE", str(Path.home() / ".linkedin-chrome-profile"))


def probe_browser() -> dict[str, Any]:
    url = _cdp_url()
    managed, backend, unit_path = _browser_service_managed()
    reachable = False
    browser: str | None = None
    health_error: str | None = None
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if isinstance(body, dict):
            reachable = True
            browser = body.get("Browser")
    except urllib.error.URLError as exc:
        health_error = str(exc.reason or exc)
    except (json.JSONDecodeError, TimeoutError, OSError) as exc:
        health_error = str(exc)

    restart_hint = "bin/browser-service install"
    if not managed:
        restart_hint = "bin/browser-service install  (or ./install.sh)"
    return {
        "url": url,
        "reachable": reachable,
        "running": reachable,
        "browser": browser,
        "profile": _chrome_profile(),
        "health_error": health_error,
        "managed": managed,
        "service_backend": backend,
        "service_unit_path": str(unit_path) if unit_path else None,
        "auto_start_on_reboot": managed,
        "restart_hint": restart_hint,
    }


def format_browser_lines() -> list[str]:
    browser = probe_browser()
    lines: list[str] = []
    if browser.get("running"):
        name = browser.get("browser") or "Chrome"
        backend = browser.get("service_backend")
        managed_s = f"  via {backend}" if backend else ""
        lines.append(f"  Chrome CDP  running{managed_s}  ({browser['url']})")
        lines.append(f"    browser    {name}")
        lines.append(f"    profile    {browser.get('profile')}")
    else:
        err = browser.get("health_error")
        hint = browser.get("restart_hint", "bin/browser-service install")
        extra = f" — {err}" if err else ""
        lines.append(f"  Chrome CDP  not running{extra}")
        lines.append(f"    restart: {hint}")
    if browser.get("managed"):
        lines.append(
            f"    auto-start  {browser.get('service_backend')}  ({browser.get('service_unit_path')})"
        )
    elif not browser.get("auto_start_on_reboot"):
        lines.append("    auto-start  not registered (run bin/browser-service install)")
    return lines


def format_full_status_lines() -> list[str]:
    lines = [f"── Chrome (CDP port {_cdp_port()}) ─────────────────"]
    lines.extend(format_browser_lines())
    lines.append("── Cron sweeps ────────────────────────────────────")
    lines.extend(format_sweep_lines())
    return lines


def main() -> int:
    for line in format_full_status_lines():
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
