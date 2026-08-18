"""Tests for the seatless 429's multi-contact rendering.

`handle_api_error` prints the server's `detail` verbatim for a 429, which is
right: the server owns the wording and there must not be a second place that
composes it. The one exception is the seat refusal when several people can grant
it — the server has to run their names together inside one sentence, which is
the least legible shape for the only part the reader has to act on. The refusal
carries them structurally too, so they get listed.

`tests/test_quota_refusal_message.py` covers the verbatim path this sits on top of.
"""

import pytest

from tl_cli.client.errors import ApiError, handle_api_error

SEATS_URL = "https://app.thoughtleaders.io/#/settings/profile?tab=organization"


def _render(error: ApiError, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        handle_api_error(error)
    assert exc.value.code == 3
    return " ".join(capsys.readouterr().err.split())  # undo console wrapping


def _no_seat(admins: list[dict[str, str]]) -> ApiError:
    names = ", ".join(f"{a['name']} ({a['email']})" for a in admins)
    detail = (
        "Your organization is on a paid plan, but your user has no CLI seat. "
        f"Ask {names} to assign you one: {SEATS_URL}"
    )
    return ApiError(
        429,
        detail,
        raw={
            "detail": detail,
            "_billing_no_seat": True,
            "_billing_can_manage_seats": False,
            "_billing_seat_admins": admins,
            "_billing_seats_url": SEATS_URL,
        },
    )


class TestSeatlessRefusal:
    def test_several_contacts_are_listed_rather_than_run_together(self, capsys):
        out = _render(
            _no_seat(
                [
                    {"name": "Vaibhav Sisinty", "email": "vaibhav@outskill.com", "role": "owner"},
                    {"name": "Amir Bar", "email": "amir@outskill.com", "role": "admin"},
                ]
            ),
            capsys,
        )
        assert "No CLI seat." in out
        assert "· Vaibhav Sisinty <vaibhav@outskill.com>" in out
        assert "· Amir Bar <amir@outskill.com>" in out
        assert SEATS_URL in out
        # Never the pre-fix wording: nothing is rate limiting them, and waiting
        # will never unblock them.
        assert "Rate limited" not in out

    def test_a_single_contact_is_left_to_the_server_sentence(self, capsys):
        # One name reads fine inline, so this stays on the verbatim path rather
        # than growing a second renderer for it.
        out = _render(
            _no_seat([{"name": "Vaibhav Sisinty", "email": "vaibhav@outskill.com", "role": "owner"}]),
            capsys,
        )
        assert "Ask Vaibhav Sisinty (vaibhav@outskill.com) to assign you one" in out
        assert "No CLI seat." not in out

    def test_a_self_serve_refusal_is_left_alone(self, capsys):
        detail = (
            "Your organization is on a paid plan, but your user has no CLI seat. "
            f"You are an admin here, so you can assign one to yourself on your team page: {SEATS_URL}"
        )
        out = _render(
            ApiError(
                429,
                detail,
                raw={
                    "detail": detail,
                    "_billing_no_seat": True,
                    "_billing_can_manage_seats": True,
                    "_billing_seat_admins": [],
                },
            ),
            capsys,
        )
        assert "you can assign one to yourself" in out
        assert "Ask an owner or admin" not in out

    def test_a_bare_429_is_untouched(self, capsys):
        assert "Rate limited." in _render(ApiError(429, "", raw=None), capsys)
