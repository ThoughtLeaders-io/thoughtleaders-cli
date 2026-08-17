"""Tests for what a 429 quota refusal actually tells the user.

Both server-side quota gates refuse with 429 and put the entire remedy into
`detail`: which cap was hit, how much of it is spent, and when it frees up. The
user's next action differs per gate — wait out a rolling window, buy credits,
or ask an org admin for a seat — so a generic "rate limited" line is not a
smaller version of the message, it is the wrong message.
"""

import pytest

from tl_cli.client.errors import ApiError, handle_api_error


def _render(error: ApiError, capsys) -> str:
    with pytest.raises(SystemExit) as exc:
        handle_api_error(error)
    assert exc.value.code == 3
    return " ".join(capsys.readouterr().err.split())  # undo console wrapping


class TestQuotaRefusalMessage:
    def test_premium_data_quota_detail_reaches_the_user(self, capsys):
        detail = (
            "Premium data quota reached: your organization has used 100 of 100 "
            "premium-data rows in the last 24h. Wait ~3.2h until the oldest call "
            "rolls off the window (2026-08-17T14:02:11+00:00)."
        )
        out = _render(
            ApiError(429, detail, raw={"detail": detail, "code": "quota_exhausted"}),
            capsys,
        )
        assert "100 of 100 premium-data rows" in out
        assert "Wait ~3.2h" in out

    def test_per_user_credit_quota_detail_reaches_the_user(self, capsys):
        detail = (
            "Per-user CLI credit quota reached: 1236.32 of 1200.00 credits used this "
            "session (5h window). Wait ~5.0h until your session resets "
            "(2026-08-17T16:21:13+00:00); you can then spend up to 1200.00 credits "
            "again. Or buy credits to continue without waiting: "
            "https://app.thoughtleaders.io/billing"
        )
        out = _render(
            ApiError(429, detail, raw={"detail": detail, "code": "quota_exhausted"}),
            capsys,
        )
        assert "1236.32 of 1200.00 credits" in out
        # The remedy is the point: without it the user cannot tell that buying
        # credits skips the wait.
        assert "buy credits" in out

    def test_seatless_refusal_names_the_remedy(self, capsys):
        detail = (
            "No CLI seat is assigned to your user in this organization. Ask an "
            "organization owner or admin to assign you a seat: "
            "https://app.thoughtleaders.io/billing"
        )
        out = _render(
            ApiError(429, detail, raw={"detail": detail, "code": "quota_exhausted"}),
            capsys,
        )
        assert "assign you a seat" in out

    def test_bare_429_keeps_the_generic_wording(self, capsys):
        # An edge/WAF rate limit carries no detail; there is nothing to explain.
        out = _render(ApiError(429, "", raw=None), capsys)
        assert "Rate limited." in out
