"""Tests for the Industry Weekly row in `tl whoami`.

Membership is absent from the response whenever it can't be determined, so the
renderers must treat that as unknown and print nothing — never a "not
subscribed" the reader would take as fact.
"""

import io
from contextlib import redirect_stdout

from tl_cli.commands.whoami import _newsletter_subscribed, _render_whoami, _render_whoami_md


def _payload(newsletter=None) -> dict:
    data = {
        "user": {"email": "a@x.test", "first_name": "A", "last_name": "B", "date_joined": "2022-05-08T10:12:00+00:00"},
        "profile": {"flags": ["advertiser"], "is_paid": True, "persona": None},
        "organization": {"name": "Org", "plan": "Pro"},
        "associated_profiles": [],
        "brands": [],
    }
    if newsletter is not None:
        data["newsletter"] = newsletter
    return data


def _render(fn, data: dict) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        fn(data)
    return buffer.getvalue()


class TestNewsletterSubscribed:
    def test_true_when_subscribed(self):
        assert _newsletter_subscribed(_payload({"subscribed": True})) is True

    def test_false_when_not_subscribed(self):
        assert _newsletter_subscribed(_payload({"subscribed": False})) is False

    def test_none_when_key_absent(self):
        assert _newsletter_subscribed(_payload()) is None

    def test_none_when_block_is_missing_the_field(self):
        assert _newsletter_subscribed(_payload({})) is None

    def test_none_when_block_is_not_an_object(self):
        assert _newsletter_subscribed(_payload("yes")) is None


class TestRenderWhoami:
    def test_subscribed_is_shown(self):
        assert "subscribed" in _render(_render_whoami, _payload({"subscribed": True}))

    def test_non_subscriber_is_shown_as_not_subscribed(self):
        assert "not subscribed" in _render(_render_whoami, _payload({"subscribed": False}))

    def test_unknown_prints_no_newsletter_row(self):
        out = _render(_render_whoami, _payload())
        assert "subscribed" not in out
        assert "Weekly" not in out

    def test_unrelated_rows_still_render(self):
        out = _render(_render_whoami, _payload({"subscribed": True}))
        assert "advertiser" in out


class TestRenderWhoamiMd:
    def test_subscribed_is_shown(self):
        assert "**Industry Weekly:** subscribed" in _render(_render_whoami_md, _payload({"subscribed": True}))

    def test_non_subscriber_is_shown_as_not_subscribed(self):
        out = _render(_render_whoami_md, _payload({"subscribed": False}))
        assert "**Industry Weekly:** not subscribed" in out

    def test_unknown_prints_no_newsletter_row(self):
        assert "Industry Weekly" not in _render(_render_whoami_md, _payload())
