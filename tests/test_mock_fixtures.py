"""Tests for outreach/mock/fixtures/*.json loader."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from outreach.mock import fixtures_loader as fl  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_fixture_cache() -> None:
    fl.reload_fixtures()
    yield
    fl.reload_fixtures()


def test_load_happy_path_fixture() -> None:
    cases = fl.load_test_cases()
    assert "happy_path" in cases
    tc = cases["happy_path"]
    assert tc["end_condition"] == "meeting_scheduled"
    assert len(tc["replies"]) == 5
    assert tc["prospect"]["name"] == "Alex Chen"


def test_load_regression_specs_from_fixture() -> None:
    specs = fl.load_regression_specs()
    hp = specs["happy_path"]
    assert len(hp["rounds"]) == 6
    assert hp["repeat_final"] is True
    assert hp["rounds"][0]["allowed_actions"] == frozenset({"send_followup_message"})
    assert hp["profile_url"].endswith("/alex-chen-softeng/")


def test_list_case_summaries_for_dashboard() -> None:
    rows = fl.list_case_summaries()
    assert len(rows) >= 1
    assert rows[0]["case_id"] == "happy_path"
    assert rows[0]["non_null_replies"] == 5
