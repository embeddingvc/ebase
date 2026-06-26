"""Unit tests for connection-sync acceptance heuristics."""

from outreach.browser import (
    connection_accepted_from_signals,
    connection_dm_ready_from_signals,
    pending_invite_aria_label_matches,
    profile_action_row_ready,
)


def test_connection_accepted_requires_first_degree_badge():
    assert connection_accepted_from_signals(
        degree=1,
        has_pending_invite=False,
        has_connect_cta=False,
    )
    assert not connection_accepted_from_signals(
        degree=None,
        has_pending_invite=False,
        has_connect_cta=False,
    )
    assert not connection_accepted_from_signals(
        degree=2,
        has_pending_invite=False,
        has_connect_cta=False,
    )


def test_connection_accepted_rejects_pending_or_connect_cta():
    assert not connection_accepted_from_signals(
        degree=1,
        has_pending_invite=True,
        has_connect_cta=False,
    )
    assert not connection_accepted_from_signals(
        degree=1,
        has_pending_invite=False,
        has_connect_cta=True,
    )


def test_profile_action_row_ready():
    assert profile_action_row_ready(
        has_connect=False,
        has_more=True,
        has_follow=False,
        has_pending=False,
        has_message=False,
    )
    assert not profile_action_row_ready(
        has_connect=False,
        has_more=False,
        has_follow=False,
        has_pending=False,
        has_message=False,
    )


def test_pending_invite_aria_label_matches_filiberto_markup():
    label = "Pending, click to withdraw invitation sent to Filiberto Diaz"
    assert pending_invite_aria_label_matches(label)


def test_connection_dm_ready_rejects_message_when_pending():
    assert not connection_dm_ready_from_signals(
        degree=None,
        has_pending_invite=True,
        has_connect_cta=False,
        has_profile_message_cta=True,
    )


def test_connection_dm_ready_allows_message_fallback_without_badge():
    assert connection_dm_ready_from_signals(
        degree=None,
        has_pending_invite=False,
        has_connect_cta=False,
        has_profile_message_cta=True,
    )
    assert not connection_dm_ready_from_signals(
        degree=None,
        has_pending_invite=True,
        has_connect_cta=False,
        has_profile_message_cta=True,
    )
