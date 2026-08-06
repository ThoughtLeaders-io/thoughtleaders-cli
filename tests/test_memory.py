"""Tests for `tl memory show / add / set`."""

from unittest.mock import patch

from typer.testing import CliRunner

from tl_cli.commands import memory as memory_mod
from tl_cli.commands.memory import app as memory_app
from tl_cli.main import app as root_app

runner = CliRunner()


class _FakeClient:
    """Records get()/post() calls and returns a fixed payload."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.gets: list[tuple[str, dict]] = []
        self.posts: list[tuple[str, dict]] = []
        self.post_timeouts: list[float | None] = []

    def get(self, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
        self.gets.append((path, params or {}))
        return self.payload

    def post(self, path: str, json_body: dict | None = None, timeout: float | None = None) -> dict:
        self.posts.append((path, json_body or {}))
        self.post_timeouts.append(timeout)
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

    def test_merge_gets_more_than_the_default_timeout(self) -> None:
        """The merge rewrites the whole memory before answering, so it must not be
        held to the client's ordinary per-request ceiling."""
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["add", "A new fact.", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.post_timeouts == [memory_mod._ADD_TIMEOUT_SECONDS]
        assert memory_mod._ADD_TIMEOUT_SECONDS > 30.0


class TestMemorySet:
    def test_posts_the_blob(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "A clean rewrite.", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.posts == [("/memory", {"memory": "A clean rewrite."})]

    def test_byte_order_mark_is_not_stored(self, tmp_path) -> None:
        """An editor that prefixes a BOM must not plant an invisible character at the
        head of the memory — it is not whitespace, so nothing downstream removes it."""
        blob = tmp_path / "memory.txt"
        blob.write_text("From a file.\n", encoding="utf-8-sig")
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", str(blob), "--json"])
        assert result.exit_code == 0, result.output
        assert fake.posts == [("/memory", {"memory": "From a file."})]

    def test_reads_from_file(self, tmp_path) -> None:
        """A text file ends with a newline that is no part of the memory."""
        blob = tmp_path / "memory.txt"
        blob.write_text("From a file.\n", encoding="utf-8")
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
        # Two different mistakes, so two different messages: "not both" is nonsense
        # advice for someone who passed neither.
        assert "--from-file" in neither.output and "not both" not in neither.output
        assert "not both" in both.output
        assert fake.posts == []

    def test_missing_file_is_an_error_before_any_request(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", "does-not-exist.txt"])
        assert result.exit_code == 1
        assert fake.posts == []

    def test_unreadable_file_encoding_is_an_error_before_any_request(self, tmp_path) -> None:
        """A non-text file must fail as a read error, not as a decode traceback
        escaping the command."""
        blob = tmp_path / "memory.bin"
        blob.write_bytes(b"\xff\xfe\x00binary")
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", str(blob), "--json"])
        assert result.exit_code == 1
        # Asserted on the fixed prefix, not the path: Rich wraps a long tmp_path
        # mid-token at the console width.
        assert "could not read" in result.output
        assert fake.posts == []

    def test_warns_when_the_replacement_did_not_fit(self) -> None:
        """Text past the size limit is dropped on the way in; the stored length alone
        does not tell the user their replacement was cut."""
        payload = _payload() | {"profile_memory": "kept", "chars": 4}
        fake = _FakeClient(payload)
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "kept and then some more", "--json"])
        assert result.exit_code == 0, result.output
        assert "Warning" in result.output

    def test_no_warning_when_the_replacement_was_stored_whole(self) -> None:
        payload = _payload() | {"profile_memory": "A clean rewrite.", "chars": 16}
        fake = _FakeClient(payload)
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "A clean rewrite.", "--json"])
        assert result.exit_code == 0, result.output
        assert "Warning" not in result.output

    def test_blank_text_will_not_erase_the_memory(self) -> None:
        """`set` replaces without a shrink guard, so a stray empty argument would
        otherwise wipe the whole memory in one call."""
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "   "])
        assert result.exit_code == 1
        assert fake.posts == []

    def test_empty_file_will_not_erase_the_memory(self, tmp_path) -> None:
        """A --from-file target that was never written is a mistake, not a request
        to erase — the likeliest way to lose a memory by accident."""
        blob = tmp_path / "memory.txt"
        blob.write_text("\n\n", encoding="utf-8")
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", str(blob)])
        assert result.exit_code == 1
        assert "erase" in result.output
        assert fake.posts == []

    def test_bracketed_path_does_not_break_the_error_message(self, tmp_path) -> None:
        """Paths are arbitrary text; a bracketed directory name must not turn a
        read failure into a rendering failure."""
        odd = tmp_path / "[draft]"
        odd.mkdir()
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(memory_app, ["set", "--from-file", str(odd / "gone.txt")])
        assert result.exit_code == 1
        assert "could not read" in result.output
        assert fake.posts == []


class TestMemoryIsReachableFromTheRootApp:
    """The other cases drive the sub-app directly, so none of them would notice the
    group never being mounted — `tl memory ...` is the only invocation users have."""

    def test_show_runs_as_tl_memory_show(self) -> None:
        fake = _FakeClient(_payload())
        with patch.object(memory_mod, "get_client", return_value=fake):
            result = runner.invoke(root_app, ["memory", "show", "--json"])
        assert result.exit_code == 0, result.output
        assert fake.gets == [("/memory", {})]
