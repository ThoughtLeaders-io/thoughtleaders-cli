"""Tests for `tl channels look-alike` (the methodology audience/topic look-alike).

`look-alike` now hits the dedicated `/lookalike` endpoint (not `/similar`).
These tests assert the command wiring: the endpoint path, the server-side vs
client-side filter split, the `id`→`channel_id` rename, and that the 0–100
score is shown as-is (not rescaled like `similar`'s 0–1 score).
"""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands import channels as channels_mod
from tl_cli.commands.channels import _apply_client_side_filters
from tl_cli.commands.channels import app as channels_app

runner = CliRunner()


class _FakeClient:
    """Records get() calls and returns a fixed payload (which the command mutates in place)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.calls.append((path, params or {}))
        return self.payload

    def close(self) -> None:
        pass


def _payload() -> dict:
    return {
        "results": [
            {"id": 1, "name": "A", "score": 88.5, "subscribers": 100_000, "category": 5},
            {"id": 2, "name": "B", "score": 50.0, "subscribers": 5_000, "category": 7},
        ],
        "total": 2,
        "channel": {"id": 999, "name": "Seed"},
        "_breadcrumbs": [],
    }


class TestApplyClientSideFilters:
    def test_category_keeps_matching(self) -> None:
        rows = [{"id": 1, "category": 5}, {"id": 2, "category": 7}]
        assert [r["id"] for r in _apply_client_side_filters(rows, {"category": "5"})] == [1]

    def test_subscriber_band(self) -> None:
        rows = [{"id": 1, "subscribers": 100_000}, {"id": 2, "subscribers": 5_000}]
        assert [r["id"] for r in _apply_client_side_filters(rows, {"min-subs": "10000"})] == [1]
        assert [r["id"] for r in _apply_client_side_filters(rows, {"max-subs": "10000"})] == [2]

    def test_exclude_ids(self) -> None:
        rows = [{"id": 1}, {"id": 2}, {"id": 3}]
        assert [r["id"] for r in _apply_client_side_filters(rows, {"exclude": "2,3"})] == [1]

    def test_no_filters_is_identity(self) -> None:
        rows = [{"id": 1}, {"id": 2}]
        assert _apply_client_side_filters(rows, {}) == rows


class TestLookAlikeCommand:
    def test_endpoint_and_filter_split(self) -> None:
        payload = _payload()
        fake = _FakeClient(payload)
        with patch.object(channels_mod, "get_client", return_value=fake):
            result = runner.invoke(
                channels_app,
                ["look-alike", "999", "msn:yes", "category:5", "min-subs:10000", "--json"],
            )
        assert result.exit_code == 0, result.output
        assert len(fake.calls) == 1
        path, params = fake.calls[0]
        assert path == "/channels/999/lookalike"
        assert params.get("msn") == "yes"  # server-side
        assert params.get("limit") == "20"
        assert "category" not in params  # client-side, never sent to server
        assert "min-subs" not in params
        # category:5 + min-subs:10000 leave only row 1, and id is renamed.
        assert [r["channel_id"] for r in payload["results"]] == [1]
        assert "id" not in payload["results"][0]

    def test_created_since_is_server_side(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(channels_mod, "get_client", return_value=fake):
            result = runner.invoke(channels_app, ["look-alike", "999", "created-since:2024", "--json"])
        assert result.exit_code == 0, result.output
        _, params = fake.calls[0]
        assert params.get("created-since") == "2024"

    def test_score_not_rescaled(self) -> None:
        # `similar` turns a 0–1 score into a percentage; look-alike's score is
        # already a 0–100 composite and must be left untouched.
        payload = _payload()
        fake = _FakeClient(payload)
        with patch.object(channels_mod, "get_client", return_value=fake):
            result = runner.invoke(channels_app, ["look-alike", "999"])
        assert result.exit_code == 0, result.output
        assert payload["results"][0]["score"] == 88.5
