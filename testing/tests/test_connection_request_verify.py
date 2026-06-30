"""Unit tests for post-submit connection-invite verification heuristics."""

from outreach.browser import (
    connection_invite_failure_reason,
    connection_invite_success_in_text,
)


def test_connection_invite_failure_reason_weekly_limit():
    text = "You've reached the weekly invitation limit"
    assert connection_invite_failure_reason(text) == (
        "LinkedIn weekly invitation limit reached."
    )


def test_connection_invite_failure_reason_verification():
    text = "Let's verify it's really you before you connect"
    assert connection_invite_failure_reason(text) == (
        "LinkedIn requested identity verification before sending invitations."
    )


def test_connection_invite_failure_reason_none_for_benign_text():
    assert connection_invite_failure_reason("Connect with Alex Chen") is None


def test_connection_invite_success_in_text_toast():
    assert connection_invite_success_in_text("Your invitation to Alex was sent.")
    assert connection_invite_success_in_text("Invitation sent")


def test_connection_invite_success_in_text_negative():
    assert not connection_invite_success_in_text("Add a note to your invitation")
