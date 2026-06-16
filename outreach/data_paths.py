"""
Live outreach data tree: path resolution + JSON I/O helpers.

Shared by the cron scheduler modules (``cron/``) and any other production
code that reads or writes the outreach data tree. The production core has no
mock awareness — ``OUTREACH_DATA_ROOT`` exists so tests (and the regression
harness in ``testing/``) can point the helpers at another directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def outreach_base() -> Path:
    """Outreach data root.

    Precedence:

    1. ``OUTREACH_DATA_ROOT`` env override (tests, regression harness).
    2. Default — ``outreach/`` (live operator data).
    """
    override = os.environ.get("OUTREACH_DATA_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return REPO_ROOT / "outreach"


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _atomic_write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
