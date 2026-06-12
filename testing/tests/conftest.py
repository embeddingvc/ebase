"""Shared sys.path setup for the testing suite.

The suite spans two roots:

- core repo root  — ``outreach.*`` production code, ``cron.*`` scheduler,
  ``tools/`` live helpers (``rate_limits``, ``notify``)
- ``testing/``    — ``web.*`` dashboard, ``outreach.mock`` fixtures
  (namespace-package portion), ``tools/mock.py`` + mock MCP server

Both roots are inserted so ``outreach`` resolves as a namespace package that
merges ``<core>/outreach`` and ``testing/outreach``.
"""

from __future__ import annotations

import sys
from pathlib import Path

TESTING_ROOT = Path(__file__).resolve().parent.parent
CORE_ROOT = TESTING_ROOT.parent

for _p in (
    str(CORE_ROOT),
    str(TESTING_ROOT),
    str(CORE_ROOT / "tools"),
    str(TESTING_ROOT / "tools"),
):
    if _p not in sys.path:
        sys.path.insert(0, _p)
