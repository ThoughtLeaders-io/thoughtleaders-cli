"""Tests for `tl memory show / add / set`."""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands import memory as memory_mod
from tl_cli.commands.memory import app as memory_app

runner = CliRunner()


class _FakeClient:
    """Records get()/post() calls and returns a fixed payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        self.gets.append((path, params or {}))
        return self.payload

    def post(self, path: str, json_body: dict | None = None) -> dict:
        self.posts.append((path, json_body or {}))
        return self.payload

    def close(self) -> None:
        pass


def _payload() -> dict:
    return {
        "profile_id": 9378,
        "profile_memory": "Runs a finance channel.",
        "chars": 23,
        "updated_at": "2026-08-03T10:00:00+00:00",
        "brand_rail_preferences": {"block_brands": ["acme"]},
        "usage": {"credits_charged": 0, "balance_remaining": 100},
    }


class TestMemoryShow:
    def test_gets_own_memory(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["show", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.gets == [("/memory", {})]

    def test_profile_id_is_passed_as_a_param(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["show", "--profile-id", "8871", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.gets == [("/memory", {"profile_id": 8871})]


class TestMemoryAdd:
    def test_posts_the_fact(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["add", "Stopped doing finance sponsorships.", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.posts == [("/memory", {"fact": "Stopped doing finance sponsorships."})]

    def test_empty_fact_rejected_before_any_request(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["add", "   "])
        assert result.exit_code == 1
        assert fake.posts == []


class TestMemorySet:
    def test_posts_the_blob(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "A clean rewrite.", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.posts == [("/memory", {"memory": "A clean rewrite."})]

    def test_reads_from_file(self, tmp_path) -> None:
        blob = tmp_path / "memory.txt"
        blob.write_text("From a file.", encoding="utf-8")
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", str(blob), "--json"])
        assert result.exit_code == 0, result.output
        assert fake.posts == [("/memory", {"memory": "From a file."})]

    def test_requires_exactly_one_source(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            neither = runner.invoke(memory_app, ["set"])
            both = runner.invoke(memory_app, ["set", "inline", "--from-file", "x.txt"])
        assert neither.exit_code == 1
        assert both.exit_code == 1
        assert fake.posts == []

    def test_missing_file_is_an_error_before_any_request(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", "does-not-exist.txt"])
        assert result.exit_code == 1
        assert fake.posts == []
