"""Tests for `tl brands winner-channels`.

Asserts the command wiring: the endpoint path, that only the known filters
(tpp / msn / since / created-since) are forwarded as query params, the limit,
and the `id`→`channel_id` rename (order preserved — the server already ranks by
renewal count).
"""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands import brands as brands_mod
from tl_cli.commands.brands import app as brands_app

runner = CliRunner()


class _FakeClient:
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
            {"id": 10, "name": "Big", "sponsorships": 15, "subscribers": 100_000, "msn": True, "tpp": True},
            {"id": 11, "name": "Small", "sponsorships": 6, "subscribers": 20_000, "msn": False, "tpp": False},
        ],
        "total": 2,
        "brand": {"id": 6037, "name": "Nike"},
        "_breadcrumbs": [],
    }


class TestWinnerChannelsCommand:
    def test_endpoint_params_and_rename(self) -> None:
        payload = _payload()
        fake = _FakeClient(payload)
        with patch.object(brands_mod, "get_client", return_value=fake):
            result = runner.invoke(
                brands_app,
                ["winner-channels", "Nike", "msn:yes", "since:2023-01-01", "tpp:no", "--json", "--limit", "30"],
            )
        assert result.exit_code == 0, result.output
        assert len(fake.calls) == 1
        path, params = fake.calls[0]
        assert path == "/brands/Nike/winner-channels"
        assert params.get("msn") == "yes"
        assert params.get("since") == "2023-01-01"
        assert params.get("tpp") == "no"
        assert params.get("limit") == "30"
        # Order preserved (server ranks by count), id renamed to channel_id.
        assert [r["channel_id"] for r in payload["results"]] == [10, 11]
        assert "id" not in payload["results"][0]

    def test_only_known_filters_forwarded(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(brands_mod, "get_client", return_value=fake):
            result = runner.invoke(brands_app, ["winner-channels", "Nike", "bogus:1", "--json"])
        assert result.exit_code == 0, result.output
        _, params = fake.calls[0]
        assert "bogus" not in params
        assert params.get("limit") == "50"  # default

    def test_created_since_forwarded(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(brands_mod, "get_client", return_value=fake):
            result = runner.invoke(brands_app, ["winner-channels", "Nike", "created-since:2024-06"])
        assert result.exit_code == 0, result.output
        _, params = fake.calls[0]
        assert params.get("created-since") == "2024-06"
