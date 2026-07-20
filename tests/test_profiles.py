"""Tests for `tl profiles update`."""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands import profiles as profiles_mod
from tl_cli.commands.profiles import app as profiles_app

runner = CliRunner()


class _FakeClient:
    """Records post() calls and returns a fixed payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def post(self, path: str, json_body: dict | None = None) -> dict:
        self.calls.append((path, json_body or {}))
        return self.payload

    def close(self) -> None:
        pass


def _payload() -> dict:
    return {
        "results": [{"id": 8871, "organization_name": "Acme", "superuser_notes": "VIP"}],
        "total": 1,
        "usage": {"credits_charged": 0, "balance_remaining": 100},
    }


class TestProfilesUpdate:
    def test_posts_fields_to_edit_endpoint(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(profiles_mod, "get_client", return_value=fake):
            result = runner.invoke(
                profiles_app,
                ["update", "8871", '{"superuser_notes": "VIP"}', "--json"],
            )
        assert result.exit_code == 0, result.output
        assert fake.calls == [("/profiles/8871/edit", {"superuser_notes": "VIP"})]

    def test_null_clears_the_field(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(profiles_mod, "get_client", return_value=fake):
            result = runner.invoke(profiles_app, ["update", "8871", '{"superuser_notes": null}', "--json"])
        assert result.exit_code == 0, result.output
        assert fake.calls[0][1] == {"superuser_notes": None}

    def test_invalid_json_rejected_before_any_request(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(profiles_mod, "get_client", return_value=fake):
            result = runner.invoke(profiles_app, ["update", "8871", "{not json"])
        assert result.exit_code == 1
        assert fake.calls == []

    def test_non_object_json_rejected(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(profiles_mod, "get_client", return_value=fake):
            result = runner.invoke(profiles_app, ["update", "8871", '["superuser_notes"]'])
        assert result.exit_code == 1
        assert fake.calls == []
