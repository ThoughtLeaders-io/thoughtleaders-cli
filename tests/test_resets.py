"""Tests for `tl resets` and the usage-reset hint on credit/session refusals.

Spending a reset is always the user's explicit choice: `tl resets use` asks
first, and a refusal only names the command, never spends one.
"""

from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from tl_cli.client.errors import ApiError, handle_api_error
from tl_cli.commands import resets as resets_mod
from tl_cli.commands.resets import app as resets_app

runner = CliRunner()


class _FakeClient:
    def __init__(self, get_payload: dict | None = None, post_result: dict | Exception | None = None) -> None:
        self.get_payload = get_payload or {}
        self.post_result = post_result
        self.calls: list[tuple[str, str]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append(("GET", path))
        return self.get_payload

    def post(self, path: str, json_body: dict | None = None) -> dict:
        self.calls.append(("POST", path))
        if isinstance(self.post_result, Exception):
            raise self.post_result
        return self.post_result or {}

    def close(self) -> None:
        pass


def _resets_payload(**overrides) -> dict:
    data = {
        "enabled": True,
        "eligible": True,
        "bonus_resets": 3,
        "expiry_days": 90,
        "available": [
            {"id": 1, "source": "welcome", "granted_at": "2026-10-01T10:00:00Z", "expires_at": "2026-12-30T10:00:00Z"},
            {"id": 2, "source": "referral_bonus", "granted_at": "2026-10-20T10:00:00Z", "expires_at": "2027-01-18T10:00:00Z"},
        ],
        "history": [
            {"id": 3, "source": "referral_signup", "status": "used", "granted_at": "2026-09-01T10:00:00Z",
             "expires_at": "2026-11-30T10:00:00Z", "used_at": "2026-09-15T10:00:00Z"},
            {"id": 4, "source": "admin_grant", "status": "capped", "granted_at": "2026-08-01T10:00:00Z",
             "expires_at": "2026-10-30T10:00:00Z", "used_at": None},
        ],
        "referral_link": "https://app.thoughtleaders.io/r/abc123",
        "referrals": {"made": 4, "valid": 1},
    }
    data.update(overrides)
    return data


def _flat(text: str) -> str:
    return " ".join(text.split())


class TestResetsList:
    def test_renders_available_history_link_and_referrals(self, capsys):
        resets_mod._render_resets(_resets_payload())
        out = _flat(capsys.readouterr().out)
        assert "Usage resets available: 2" in out
        assert "Gift from ThoughtLeaders" in out
        assert "Your invitee's first proposal or payment" in out
        assert "2026-12-30" in out
        assert "Your invite was accepted" in out
        assert "Used" in out and "2026-09-15" in out
        assert "Added by support" in out and "Over the limit" in out
        assert ("Invite a friend outside your organization. You'll get a free reset when they join: "
                "https://app.thoughtleaders.io/r/abc123") in out
        assert "4 users signed up with your link" in out
        assert "1 user earned you a reset" in out
        assert "tl resets use" in out
        assert "cr " not in out

    def test_zero_referral_counts_are_left_out(self, capsys):
        resets_mod._render_resets(_resets_payload(referrals={"made": 2, "valid": 0}))
        out = _flat(capsys.readouterr().out)
        assert "2 users signed up with your link" in out
        assert "earned you a reset" not in out

    def test_disabled_prints_one_line(self, capsys):
        resets_mod._render_resets({"enabled": False})
        out = capsys.readouterr().out.strip()
        assert out == resets_mod.DISABLED_MESSAGE

    def test_ineligible_plan_says_so_and_does_not_suggest_spending(self, capsys):
        resets_mod._render_resets(_resets_payload(eligible=False))
        out = _flat(capsys.readouterr().out)
        assert "can't be spent on your current plan" in out
        assert "Spend one with" not in out

    def test_json_prints_the_response(self):
        fake = _FakeClient(get_payload=_resets_payload())
        with patch.object(resets_mod, "get_client", return_value=fake):
            result = runner.invoke(resets_app, ["--json"])
        assert result.exit_code == 0, result.output
        assert '"referral_link": "https://app.thoughtleaders.io/r/abc123"' in result.output
        assert fake.calls == [("GET", "/resets")]


USE_RESULT = {
    "weekly_before": "12.50",
    "weekly_after": "1000.00",
    "debt_repaid": "0",
    "session_reanchored": True,
    "available": 1,
}


class TestResetsUse:
    def test_yes_spends_without_asking(self):
        fake = _FakeClient(post_result=USE_RESULT)
        with patch.object(resets_mod, "get_client", return_value=fake), \
                patch.object(resets_mod, "_interactive", return_value=True), \
                patch.object(resets_mod, "detect_format", return_value="table"):
            result = runner.invoke(resets_app, ["use", "--yes"])
        assert result.exit_code == 0, result.output
        assert fake.calls == [("POST", "/resets/use")]
        out = _flat(result.output)
        assert "12.50 → 1000.00 credits" in out
        assert "5-hour session restarted" in out
        assert "Resets left: 1" in out

    def test_interactive_session_asks_and_declining_spends_nothing(self):
        fake = _FakeClient(post_result=USE_RESULT)
        with patch.object(resets_mod, "get_client", return_value=fake), \
                patch.object(resets_mod, "_interactive", return_value=True):
            result = runner.invoke(resets_app, ["use"], input="n\n")
        assert result.exit_code == 1
        assert fake.calls == []
        assert "No reset spent" in result.output

    def test_interactive_session_confirmed_spends(self):
        fake = _FakeClient(post_result=USE_RESULT)
        with patch.object(resets_mod, "get_client", return_value=fake), \
                patch.object(resets_mod, "_interactive", return_value=True):
            result = runner.invoke(resets_app, ["use", "--json"], input="y\n")
        assert result.exit_code == 0, result.output
        assert fake.calls == [("POST", "/resets/use")]

    def test_non_interactive_session_does_not_ask(self):
        fake = _FakeClient(post_result=USE_RESULT)
        with patch.object(resets_mod, "get_client", return_value=fake), \
                patch.object(resets_mod, "_interactive", return_value=False):
            result = runner.invoke(resets_app, ["use", "--json"])
        assert result.exit_code == 0, result.output
        assert '"weekly_after": "1000.00"' in result.output

    @pytest.mark.parametrize(
        ("status", "code", "exit_code"),
        [
            (400, "nothing_to_restore", 1),
            (403, "reset_not_eligible", 5),
            (403, "resets_disabled", 5),
            (409, "no_reset_available", 1),
        ],
    )
    def test_refusals_show_their_detail(self, status, code, exit_code):
        detail = f"Refused because {code}."
        error = ApiError(status, detail, raw={"code": code, "detail": detail})
        fake = _FakeClient(post_result=error)
        with patch.object(resets_mod, "get_client", return_value=fake):
            result = runner.invoke(resets_app, ["use", "--yes"])
        assert result.exit_code == exit_code
        assert detail in _flat(result.output)
        assert "Error (" not in result.output
        assert "Access denied" not in result.output


def _render_error(error: ApiError, capsys, code: int) -> str:
    with pytest.raises(SystemExit) as exc:
        handle_api_error(error)
    assert exc.value.code == code
    return _flat(capsys.readouterr().err)


class TestRefusalHint:
    def test_402_with_resets_names_the_command(self, capsys):
        raw = {"detail": "Out of credits.", "code": "insufficient_credits",
               "_billing_resets_available": 2, "_billing_reset_url": "/api/cli/v1/resets/use"}
        out = _render_error(ApiError(402, "Out of credits.", raw=raw), capsys, code=4)
        assert "You have 2 usage resets. Spend one with: tl resets use" in out

    def test_429_with_one_reset(self, capsys):
        raw = {"detail": "Session limit reached.", "code": "quota_exhausted", "_billing_resets_available": 1}
        out = _render_error(ApiError(429, "Session limit reached.", raw=raw), capsys, code=3)
        assert "You have 1 usage reset. Spend one with: tl resets use" in out

    @pytest.mark.parametrize("status,code", [(402, 4), (429, 3)])
    def test_invite_link_follows_the_reset_offer(self, capsys, status, code):
        raw = {"detail": "Refused.", "_billing_resets_available": 1,
               "_billing_invite_link": "https://app.thoughtleaders.io/r/5jXOLpkmhx/",
               "_billing_invite_url": "https://app.thoughtleaders.io/billing/?section=invite"}
        out = _render_error(ApiError(status, "Refused.", raw=raw), capsys, code=code)
        invite = ("Or invite a friend outside your organization. You'll get a free reset when they join: "
                  "https://app.thoughtleaders.io/r/5jXOLpkmhx/")
        assert invite in out
        assert out.index("tl resets use") < out.index(invite)
        assert "section=invite" not in out

    def test_no_invite_line_without_link(self, capsys):
        raw = {"detail": "Out of credits.", "code": "insufficient_credits", "_billing_resets_available": 1}
        out = _render_error(ApiError(402, "Out of credits.", raw=raw), capsys, code=4)
        assert "invite a friend" not in out

    @pytest.mark.parametrize("raw", [
        {"detail": "Out of credits.", "code": "insufficient_credits"},
        {"detail": "Out of credits.", "code": "insufficient_credits", "_billing_resets_available": 0},
        None,
    ])
    def test_no_hint_without_resets(self, capsys, raw):
        out = _render_error(ApiError(402, "Out of credits.", raw=raw), capsys, code=4)
        assert "tl resets use" not in out
