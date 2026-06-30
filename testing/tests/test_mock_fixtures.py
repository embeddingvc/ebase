"""Tests for testing/outreach/mock/fixtures/*.json loader."""

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


def test_all_fixtures_load() -> None:
    case_ids = fl.list_case_ids()
    assert case_ids == sorted(
        [
            "eager_referral",
            "ghosted_cold",
            "happy_path",
            "no_reply",
            "not_interested",
        ]
    )


def test_load_happy_path_fixture() -> None:
    cases = fl.load_test_cases()
    assert "happy_path" in cases
    tc = cases["happy_path"]
    assert tc["end_condition"] == "meeting_scheduled"
    assert len(tc["replies"]) == 5
    assert tc["prospect"]["name"] == "Alex Chen"


def test_no_reply_preserves_null_replies() -> None:
    tc = fl.load_test_cases()["no_reply"]
    assert tc["replies"][0] is not None
    assert tc["replies"][1] is None
    assert tc["replies"][2] is None


def test_ghosted_cold_all_silent_replies() -> None:
    tc = fl.load_test_cases()["ghosted_cold"]
    assert all(r is None for r in tc["replies"])


def test_eager_referral_resume_attachment() -> None:
    tc = fl.load_test_cases()["eager_referral"]
    assert len(tc["replies"]) == 3
    assert tc["prospect"]["end_goal"] == "resume_received"
    resume_reply = tc["replies"][2]
    assert resume_reply is not None
    assert resume_reply["attachments"][0]["type"] == "resume"


def test_load_regression_specs_from_fixtures() -> None:
    specs = fl.load_regression_specs()
    assert len(specs) == 5
    hp = specs["happy_path"]
    assert len(hp["rounds"]) == 6
    assert hp["repeat_final"] is True
    assert hp["profile_url"].endswith("/alex-chen-softeng/")
    ni = specs["not_interested"]
    assert ni["prospect_id"] == "jordan_kim_ml"
    assert ni["rounds"][0]["allowed_actions"] == frozenset(
        {"mark_ended", "mark_dead", "send_followup_message"}
    )


def test_get_mock_conversations_lists_all_fixtures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from web import mock_conversation as mc

    # Isolate from on-disk mock sessions so the test sees only fixture
    # placeholders (no live sessions).
    empty_mock = tmp_path / "mock_isolated"
    empty_mock.mkdir()
    monkeypatch.setattr(mc, "mock_base", lambda: empty_mock)

    data = mc.get_mock_conversations()
    assert len(data["cases"]) == 5
    assert data["total"] == 5
    assert data["live_total"] == 0
    case_ids = {s["test_case_id"] for s in data["sessions"]}
    assert case_ids == {
        "eager_referral",
        "ghosted_cold",
        "happy_path",
        "no_reply",
        "not_interested",
    }
    placeholder = next(
        s for s in data["sessions"] if s["test_case_id"] == "not_interested"
    )
    assert placeholder["live"] is False
    assert len(placeholder["scripted_replies"]) == 1


def test_list_case_summaries_for_dashboard() -> None:
    rows = fl.list_case_summaries()
    assert len(rows) == 5
    by_id = {r["case_id"]: r for r in rows}
    assert by_id["not_interested"]["prospect_name"] == "Jordan Kim"
    assert by_id["no_reply"]["non_null_replies"] == 1
    assert by_id["ghosted_cold"]["non_null_replies"] == 0
