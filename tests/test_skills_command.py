"""Tests for `tl skill list|download|update|remove` and the per-run
staleness check, with the HTTP client mocked (no network) and every
filesystem path redirected under tmp_path.

Encodes: download refuses/overwrites/replaces per the marker rule; a path
traversal in the server response aborts the whole install; update reports
"gone" skills without deleting them; remove only deletes marker-bearing
dirs; the staleness check makes at most one network call per day and is
silent on any failure.
"""

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from tl_cli import skill_registry as sr
from tl_cli.commands import skills as skills_mod
from tl_cli.commands.skills import app as skills_app

runner = CliRunner()


class _FakeClient:
    """Routes `.get(path)` to a fixed per-path response; records calls."""

    def __init__(self, responses: dict[str, dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []
        self.timeouts: list[float | None] = []

    def get(self, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
        self.calls.append((path, params or {}))
        self.timeouts.append(timeout)
        if path not in self.responses:
            raise AssertionError(f"unexpected call to {path!r} (params={params})")
        return self.responses[path]

    def close(self) -> None:
        pass


def _skill_payload(name: str, version: str, checksum: str, files: dict[str, str], **extra) -> dict:
    return {"results": {"name": name, "version": version, "checksum": checksum, "files": files, "description": "", "changelog": "", **extra}}


@pytest.fixture(autouse=True)
def _isolated_paths(tmp_path, monkeypatch):
    """Redirect every install target + registry + cache under tmp_path."""
    monkeypatch.setattr(skills_mod, "CLAUDE_SKILLS_DIR", tmp_path / "claude" / "skills")
    monkeypatch.setattr(skills_mod, "OPENCODE_SKILLS_DIR", tmp_path / "opencode" / "skills")
    monkeypatch.setattr(skills_mod, "AGENTS_SKILLS_DIR", tmp_path / "agents" / "skills")
    monkeypatch.setattr(sr, "REGISTRY_PATH", tmp_path / "config" / "skills.json")
    monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", tmp_path / "config" / "skills-check.json")
    return tmp_path


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


class TestDownload:
    def test_fresh_install_to_all_three_targets(self, tmp_path):
        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "# foo"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["installed_count"] == 3
        for t in data["targets"]:
            assert t["installed"] is True
            assert t["action"] == "installed"
            assert (Path(t["path"]) / "SKILL.md").read_text() == "# foo"

        registry = sr.read_registry()
        assert registry["skills"]["foo"]["version"] == "1.0.0"
        assert len(registry["skills"]["foo"]["paths"]) == 3

    def test_refuses_unmarked_existing_dir_without_force(self, tmp_path):
        claude_dest = tmp_path / "claude" / "skills" / "foo"
        claude_dest.mkdir(parents=True)
        (claude_dest / "mine.txt").write_text("user's own content", encoding="utf-8")

        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "# foo"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["installed_count"] == 2

        refused = [t for t in data["targets"] if not t["installed"]]
        assert len(refused) == 1
        assert refused[0]["action"] == "refused"
        # Untouched — the user's own file is still there.
        assert (claude_dest / "mine.txt").read_text() == "user's own content"
        assert not (claude_dest / "SKILL.md").exists()

    def test_force_overwrites_unmarked_dir(self, tmp_path):
        claude_dest = tmp_path / "claude" / "skills" / "foo"
        claude_dest.mkdir(parents=True)
        (claude_dest / "mine.txt").write_text("user's own content", encoding="utf-8")

        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "# foo"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--force", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["installed_count"] == 3
        assert (claude_dest / "SKILL.md").read_text() == "# foo"
        assert not (claude_dest / "mine.txt").exists()

    def test_replaces_marker_bearing_dir_without_force(self, tmp_path):
        claude_dest = tmp_path / "claude" / "skills" / "foo"
        sr.install_skill_tree({"SKILL.md": "old"}, claude_dest, name="foo", version="0.9.0", checksum="old")

        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "new"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["installed_count"] == 3
        claude_target = next(t for t in data["targets"] if "claude" in t["path"])
        assert claude_target["action"] == "replaced"
        assert (claude_dest / "SKILL.md").read_text() == "new"

    def test_path_traversal_in_response_aborts_and_writes_nothing(self, tmp_path):
        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "ok", "../evil.txt": "bad"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--json"])
        assert result.exit_code != 0
        for base in ("claude", "opencode", "agents"):
            assert not (tmp_path / base / "skills" / "foo").exists()
        assert sr.read_registry() == {"skills": {}}

    def test_all_targets_refused_exits_nonzero(self, tmp_path):
        for base in ("claude", "opencode", "agents"):
            d = tmp_path / base / "skills" / "foo"
            d.mkdir(parents=True)
            (d / "mine.txt").write_text("mine", encoding="utf-8")

        fake = _FakeClient({"/skills/foo/": _skill_payload("foo", "1.0.0", "c1", {"SKILL.md": "new"})})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["download", "foo", "--json"])
        assert result.exit_code == 1
        assert sr.read_registry() == {"skills": {}}


# ---------------------------------------------------------------------------
# download — invalid name rejected client-side (N2)
# ---------------------------------------------------------------------------


class TestDownloadInvalidName:
    @pytest.mark.parametrize("bad_name", ["../evil", "Foo", "foo/bar", "foo bar", "foo_bar", "a" * 65])
    def test_invalid_name_rejected_before_any_network_call(self, tmp_path, bad_name):
        mock_get_client = MagicMock()
        with patch.object(skills_mod, "get_client", mock_get_client):
            result = runner.invoke(skills_app, ["download", bad_name, "--json"])
        assert result.exit_code != 0
        assert not mock_get_client.called


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


class TestList:
    def test_merges_registry_and_marks_outdated(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        fake = _FakeClient(
            {"/skills/": {"results": [{"name": "foo", "version": "2.0.0", "description": "desc", "changelog": "", "updated_at": "x"}]}}
        )
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["list", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        row = data["results"][0]
        assert row["name"] == "foo"
        assert row["latest_version"] == "2.0.0"
        assert row["installed_version"] == "1.0.0"
        assert row["status"] == "outdated"

    def test_not_installed_shows_dash(self, tmp_path):
        fake = _FakeClient({"/skills/": {"results": [{"name": "bar", "version": "1.0.0", "description": ""}]}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["list", "--json"])
        assert result.exit_code == 0, result.output
        row = json.loads(result.stdout)["results"][0]
        assert row["installed_version"] == "—"
        assert row["status"] == ""

    def test_all_flag_sends_query_param(self, tmp_path):
        fake = _FakeClient({"/skills/": {"results": []}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            runner.invoke(skills_app, ["list", "--all", "--json"])
        assert fake.calls == [("/skills/", {"all": "1"})]

    def test_empty_state_friendly_message(self, tmp_path):
        # Force a non-JSON format explicitly — CliRunner's stdout isn't a
        # tty, so `detect_format` would otherwise default to "json" here.
        fake = _FakeClient({"/skills/": {"results": []}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["list", "--md"])
        assert result.exit_code == 0, result.output
        assert "No skills available for your organization" in (result.stderr or result.output)


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------


class TestUpdate:
    def test_empty_registry_is_a_friendly_no_op(self, tmp_path):
        result = runner.invoke(skills_app, ["update", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data == {"updated": [], "gone": [], "unchanged": [], "failed": []}

    def test_reports_gone_without_deleting(self, tmp_path):
        dest = tmp_path / "claude" / "skills" / "foo"
        sr.install_skill_tree({"SKILL.md": "x"}, dest, name="foo", version="1.0.0", checksum="c")
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [str(dest)], "installed_at": "x"}}})
        fake = _FakeClient({"/skills/versions/": {"results": {"foo": None}}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["update", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["gone"] == ["foo"]
        # Not deleted — files and registry entry both survive.
        assert dest.exists()
        assert "foo" in sr.read_registry()["skills"]

    def test_reinstalls_newer_version(self, tmp_path):
        dest = tmp_path / "claude" / "skills" / "foo"
        sr.install_skill_tree({"SKILL.md": "old"}, dest, name="foo", version="1.0.0", checksum="c1")
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c1", "paths": [str(dest)], "installed_at": "x"}}})
        fake = _FakeClient(
            {
                "/skills/versions/": {"results": {"foo": "2.0.0"}},
                "/skills/foo/": _skill_payload("foo", "2.0.0", "c2", {"SKILL.md": "new"}),
            }
        )
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["update", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["updated"] == ["foo"]
        assert (dest / "SKILL.md").read_text() == "new"
        assert sr.read_registry()["skills"]["foo"]["version"] == "2.0.0"

    def test_skips_unchanged(self, tmp_path):
        dest = tmp_path / "claude" / "skills" / "foo"
        sr.install_skill_tree({"SKILL.md": "same"}, dest, name="foo", version="1.0.0", checksum="c1")
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c1", "paths": [str(dest)], "installed_at": "x"}}})
        fake = _FakeClient({"/skills/versions/": {"results": {"foo": "1.0.0"}}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            result = runner.invoke(skills_app, ["update", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["unchanged"] == ["foo"]
        # No fetch of /skills/foo/ should have happened.
        assert all(path != "/skills/foo/" for path, _ in fake.calls)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_deletes_only_marked_dirs(self, tmp_path):
        marked = tmp_path / "claude" / "skills" / "foo"
        sr.install_skill_tree({"SKILL.md": "x"}, marked, name="foo", version="1.0.0", checksum="c")

        unmarked = tmp_path / "opencode" / "skills" / "foo"
        unmarked.mkdir(parents=True)
        (unmarked / "someone-elses.txt").write_text("not ours", encoding="utf-8")

        sr.write_registry(
            {
                "skills": {
                    "foo": {
                        "version": "1.0.0",
                        "checksum": "c",
                        "paths": [str(marked), str(unmarked)],
                        "installed_at": "x",
                    }
                }
            }
        )

        result = runner.invoke(skills_app, ["remove", "foo", "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["removed"] == [str(marked)]
        assert data["skipped"] == [str(unmarked)]
        assert not marked.exists()
        assert unmarked.exists()  # left untouched
        assert "foo" not in sr.read_registry()["skills"]

    def test_unknown_skill_is_an_error(self, tmp_path):
        result = runner.invoke(skills_app, ["remove", "nope", "--json"])
        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# staleness check
# ---------------------------------------------------------------------------


class TestStalenessCheck:
    def test_empty_registry_no_network_call(self, tmp_path):
        mock_get_client = MagicMock()
        with patch.object(skills_mod, "get_client", mock_get_client):
            assert skills_mod.check_skill_staleness() is None
        assert not mock_get_client.called

    def test_fresh_cache_skips_network_call(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        sr.write_staleness_cache({"foo": "1.0.0"})  # unchanged, and fresh

        mock_get_client = MagicMock()
        with patch.object(skills_mod, "get_client", mock_get_client):
            warn = skills_mod.check_skill_staleness()
        assert warn is None
        assert not mock_get_client.called

    def test_stale_cache_makes_one_call_and_warns_on_drift(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        # No cache file at all == "stale" (treated as absent).
        fake = _FakeClient({"/skills/versions/": {"results": {"foo": "2.0.0"}}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            warn = skills_mod.check_skill_staleness()
        assert warn is not None
        assert "foo" in warn
        assert "tl skill update" in warn
        assert len(fake.calls) == 1
        # Result got cached for next time.
        assert sr.read_staleness_cache()["results"] == {"foo": "2.0.0"}

    def test_any_exception_is_silent(self, tmp_path, monkeypatch):
        def _boom():
            raise RuntimeError("registry is on fire")

        monkeypatch.setattr(skills_mod, "read_registry", _boom)
        assert skills_mod.check_skill_staleness() is None


# ---------------------------------------------------------------------------
# staleness check — failure backoff (W4)
# ---------------------------------------------------------------------------


class _BoomClient:
    """A client whose `.get()` always fails, simulating an unreachable server."""

    def get(self, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
        raise RuntimeError("connection timed out")

    def close(self) -> None:
        pass


class TestStalenessCheckFailureBackoff:
    def test_network_failure_writes_failure_stamp(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        with patch.object(skills_mod, "get_client", return_value=_BoomClient()):
            warn = skills_mod.check_skill_staleness()
        assert warn is None
        cache = sr.read_staleness_cache()
        assert cache is not None
        assert cache["failed"] is True

    def test_second_call_within_backoff_window_makes_no_network_call(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        with patch.object(skills_mod, "get_client", return_value=_BoomClient()):
            assert skills_mod.check_skill_staleness() is None

        mock_get_client = MagicMock()
        with patch.object(skills_mod, "get_client", mock_get_client):
            assert skills_mod.check_skill_staleness() is None
        assert not mock_get_client.called

    def test_success_after_expired_failure_stamp_overwrites_it(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        # Seed an already-expired failure stamp so this check hits the
        # network again instead of backing off.
        sr.STALENESS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        sr.STALENESS_CACHE_PATH.write_text(
            json.dumps({"checked_at": time.time() - sr.STALENESS_FAILURE_TTL_SECONDS - 1, "failed": True}),
            encoding="utf-8",
        )

        fake = _FakeClient({"/skills/versions/": {"results": {"foo": "2.0.0"}}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            warn = skills_mod.check_skill_staleness()
        assert warn is not None
        assert "foo" in warn

        cache = sr.read_staleness_cache()
        assert cache is not None
        assert "failed" not in cache
        assert cache["results"] == {"foo": "2.0.0"}

    def test_successful_check_passes_a_short_timeout(self, tmp_path):
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        fake = _FakeClient({"/skills/versions/": {"results": {"foo": "1.0.0"}}})
        with patch.object(skills_mod, "get_client", return_value=fake):
            skills_mod.check_skill_staleness()
        assert fake.calls == [("/skills/versions/", {"names": "foo"})]
        # A background per-run check shouldn't inherit the client's full
        # 30s default — it should ask for something much shorter.
        assert fake.timeouts == [skills_mod.STALENESS_CHECK_TIMEOUT_SECONDS]
        assert skills_mod.STALENESS_CHECK_TIMEOUT_SECONDS < 30
