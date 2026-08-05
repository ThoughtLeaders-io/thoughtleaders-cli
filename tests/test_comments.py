"""Tests for the shared comment subcommands (comment-list / comment-add).

Asserts the `--organization-id` flag wiring: when passed, it is sent as the
`organization_id` query param on both list (GET) and add (POST); when omitted,
no params are sent at all.
"""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands.channels import app as channels_app

runner = CliRunner()


class _FakeClient:
    """Records calls and returns a fixed comments payload."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append(("GET", path, params))
        return self._payload()

    def post(self, path: str, json_body: dict | None = None, params: dict | None = None) -> dict:
        self.calls.append(("POST", path, params))
        return self._payload()

    @staticmethod
    def _payload() -> dict:
        return {
            "results": [
                {"id": 7, "author": "Ada L", "text": "note", "created_at": "2026-08-05T10:00:00"},
            ],
            "total": 1,
            "_breadcrumbs": [],
        }

    def close(self) -> None:
        pass


def _run(args: list[str]) -> _FakeClient:
    fake = _FakeClient()
    with patch("tl_cli.commands._comments_common.get_client", return_value=fake):
        result = runner.invoke(channels_app, args)
    assert result.exit_code == 0, result.output
    return fake


class TestCommentList:
    def test_no_org_flag_sends_no_params(self) -> None:
        fake = _run(["comment-list", "123", "--json"])
        assert fake.calls == [("GET", "/channel/123/comments", None)]

    def test_org_flag_sent_as_query_param(self) -> None:
        fake = _run(["comment-list", "123", "--organization-id", "456", "--json"])
        assert fake.calls == [("GET", "/channel/123/comments", {"organization_id": 456})]


class TestCommentAdd:
    def test_no_org_flag_sends_no_params(self) -> None:
        fake = _run(["comment-add", "123", "hello", "--json"])
        assert fake.calls == [("POST", "/channel/123/comments", None)]

    def test_org_flag_sent_as_query_param(self) -> None:
        fake = _run(["comment-add", "123", "hello", "--organization-id", "456", "--json"])
        assert fake.calls == [("POST", "/channel/123/comments", {"organization_id": 456})]
