"""Tests for `tl_cli.skill_registry`: path safety, atomic install, marker, registry.

These encode the safety properties the plan calls out explicitly:
a malicious or truncated server response cannot damage the client machine
(path safety + atomic install), and routine registry reads survive a
missing or corrupt file without crashing.
"""

import json
import time
from pathlib import Path

import pytest

from tl_cli import skill_registry as sr

# ---------------------------------------------------------------------------
# Skill name validation
# ---------------------------------------------------------------------------


class TestValidateSkillName:
    @pytest.mark.parametrize("good", ["a", "foo", "foo-bar", "foo2", "a" * 64])
    def test_accepts_valid_names(self, good):
        sr.validate_skill_name(good)  # must not raise

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "-foo",
            "Foo",
            "foo/bar",
            "foo\\bar",
            "../evil",
            "foo bar",
            "foo_bar",
            "a" * 65,
        ],
    )
    def test_rejects_invalid_names(self, bad):
        with pytest.raises(sr.InvalidSkillNameError):
            sr.validate_skill_name(bad)


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------


class TestValidateRelpath:
    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "/etc/passwd",
            "..\\evil",
            "a\\b",
            "../escape",
            "a/../../escape",
            "a/./b",
            "a//b",
            "a/",
            "/a",
            "a\x00b",
            "C:/Windows/System32/evil",
            "C:evil",
            "c:/evil",
        ],
    )
    def test_rejects_unsafe_paths(self, bad):
        with pytest.raises(sr.PathSafetyError):
            sr.validate_relpath(bad)

    @pytest.mark.parametrize("good", ["SKILL.md", "scripts/run.py", "a/b/c.txt"])
    def test_accepts_safe_paths(self, good):
        sr.validate_relpath(good)  # must not raise


class TestValidateFiles:
    def test_rejects_traversal_in_bundle(self):
        with pytest.raises(sr.PathSafetyError):
            sr.validate_files({"SKILL.md": "ok", "../../etc/passwd": "evil"})

    def test_rejects_absolute_path_in_bundle(self):
        with pytest.raises(sr.PathSafetyError):
            sr.validate_files({"SKILL.md": "ok", "/etc/passwd": "evil"})

    def test_rejects_backslash_in_bundle(self):
        with pytest.raises(sr.PathSafetyError):
            sr.validate_files({"SKILL.md": "ok", "scripts\\evil.py": "x"})

    def test_rejects_non_string_content(self):
        with pytest.raises(sr.PathSafetyError):
            sr.validate_files({"SKILL.md": 123})

    def test_accepts_clean_bundle(self):
        sr.validate_files({"SKILL.md": "ok", "scripts/run.py": "print()"})


class TestInstallSkillTreePathSafety:
    def test_traversal_path_aborts_install_nothing_written(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        files = {"SKILL.md": "ok", "../escape.txt": "evil"}
        with pytest.raises(sr.PathSafetyError):
            sr.install_skill_tree(files, target, name="myskill", version="1.0.0", checksum="abc")
        # Nothing was written: no target dir, no leftover temp/old siblings.
        assert not target.exists()
        leftovers = list(target.parent.iterdir()) if target.parent.exists() else []
        assert leftovers == []

    def test_absolute_path_aborts_install(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        files = {"SKILL.md": "ok", "/etc/passwd": "evil"}
        with pytest.raises(sr.PathSafetyError):
            sr.install_skill_tree(files, target, name="myskill", version="1.0.0", checksum="abc")
        assert not target.exists()

    def test_backslash_path_aborts_install(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        files = {"SKILL.md": "ok", "scripts\\evil.py": "x"}
        with pytest.raises(sr.PathSafetyError):
            sr.install_skill_tree(files, target, name="myskill", version="1.0.0", checksum="abc")
        assert not target.exists()


# ---------------------------------------------------------------------------
# Atomic install
# ---------------------------------------------------------------------------


class TestAtomicInstall:
    def test_fresh_install_writes_files_and_marker(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        files = {"SKILL.md": "# hello", "scripts/run.py": "print('hi')"}
        sr.install_skill_tree(files, target, name="myskill", version="1.0.0", checksum="deadbeef")

        assert (target / "SKILL.md").read_text() == "# hello"
        assert (target / "scripts" / "run.py").read_text() == "print('hi')"
        marker = json.loads((target / sr.MARKER_FILENAME).read_text())
        assert marker == {
            "name": "myskill",
            "version": "1.0.0",
            "checksum": "deadbeef",
            "managed_by": "tl",
        }
        # No leftover temp/old siblings.
        siblings = {p.name for p in target.parent.iterdir()}
        assert siblings == {"myskill"}

    def test_replaces_existing_marked_dir(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        sr.install_skill_tree({"SKILL.md": "v1"}, target, name="myskill", version="1.0.0", checksum="c1")
        sr.install_skill_tree({"SKILL.md": "v2"}, target, name="myskill", version="2.0.0", checksum="c2")

        assert (target / "SKILL.md").read_text() == "v2"
        marker = json.loads((target / sr.MARKER_FILENAME).read_text())
        assert marker["version"] == "2.0.0"
        siblings = {p.name for p in target.parent.iterdir()}
        assert siblings == {"myskill"}  # old-* / tmp-* cleaned up

    def test_mid_write_failure_leaves_previous_dir_intact(self, tmp_path):
        target = tmp_path / "install" / "myskill"
        target.mkdir(parents=True)
        (target / "SKILL.md").write_text("original content", encoding="utf-8")
        (target / sr.MARKER_FILENAME).write_text(
            json.dumps({"name": "myskill", "version": "1.0.0", "checksum": "orig", "managed_by": "tl"}),
            encoding="utf-8",
        )

        # "a" is written as a file; "a/sub.txt" then can't create its parent
        # dir because "a" already exists as a regular file — a deterministic
        # mid-loop failure with no monkeypatching required.
        files = {"SKILL.md": "new content", "a": "file", "a/sub.txt": "nested"}
        with pytest.raises(Exception):
            sr.install_skill_tree(files, target, name="myskill", version="2.0.0", checksum="new")

        # Previous directory is completely untouched.
        assert (target / "SKILL.md").read_text(encoding="utf-8") == "original content"
        marker = json.loads((target / sr.MARKER_FILENAME).read_text())
        assert marker["version"] == "1.0.0"
        # No leftover temp dirs.
        siblings = {p.name for p in target.parent.iterdir()}
        assert siblings == {"myskill"}

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "does" / "not" / "exist" / "myskill"
        sr.install_skill_tree({"SKILL.md": "hi"}, target, name="myskill", version="1.0.0", checksum="c")
        assert (target / "SKILL.md").read_text() == "hi"


# ---------------------------------------------------------------------------
# Marker
# ---------------------------------------------------------------------------


class TestMarker:
    def test_is_marked_for_true_for_matching_marker(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        sr.write_marker(d, name="foo", version="1.0.0", checksum="c")
        assert sr.is_marked_for(d, "foo") is True

    def test_is_marked_for_false_for_different_name(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        sr.write_marker(d, name="foo", version="1.0.0", checksum="c")
        assert sr.is_marked_for(d, "bar") is False

    def test_is_marked_for_false_when_no_marker(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        assert sr.is_marked_for(d, "foo") is False

    def test_is_marked_for_false_when_marker_corrupt(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / sr.MARKER_FILENAME).write_text("{not json", encoding="utf-8")
        assert sr.is_marked_for(d, "foo") is False

    def test_is_marked_for_false_when_marker_missing_keys(self, tmp_path):
        d = tmp_path / "skill"
        d.mkdir()
        (d / sr.MARKER_FILENAME).write_text(json.dumps({"name": "foo"}), encoding="utf-8")
        assert sr.is_marked_for(d, "foo") is False

    def test_is_marked_for_false_when_not_a_directory(self, tmp_path):
        f = tmp_path / "not-a-dir"
        f.write_text("x", encoding="utf-8")
        assert sr.is_marked_for(f, "foo") is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_missing_file_returns_empty_registry(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "REGISTRY_PATH", tmp_path / "skills.json")
        assert sr.read_registry() == {"skills": {}}

    def test_corrupt_file_returns_empty_registry(self, tmp_path, monkeypatch):
        path = tmp_path / "skills.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)
        assert sr.read_registry() == {"skills": {}}

    def test_wrong_shape_returns_empty_registry(self, tmp_path, monkeypatch):
        path = tmp_path / "skills.json"
        path.write_text(json.dumps({"skills": "not-a-dict"}), encoding="utf-8")
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)
        assert sr.read_registry() == {"skills": {}}

    def test_write_then_read_round_trips(self, tmp_path, monkeypatch):
        path = tmp_path / "sub" / "skills.json"
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)
        data = {"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "now"}}}
        sr.write_registry(data)
        assert sr.read_registry() == data


# ---------------------------------------------------------------------------
# Atomic write (N3): temp file + os.replace, crash-safe
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_serialization_failure_leaves_existing_file_intact(self, tmp_path, monkeypatch):
        path = tmp_path / "skills.json"
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)
        sr.write_registry({"skills": {"foo": {"version": "1.0.0", "checksum": "c", "paths": [], "installed_at": "x"}}})
        original = path.read_text(encoding="utf-8")

        # A `set` isn't JSON-serializable — json.dumps raises before any
        # file on disk is touched, so the previous content must survive.
        bad_data = {"skills": {"foo": {"paths": {1, 2, 3}}}}
        with pytest.raises(TypeError):
            sr.write_registry(bad_data)

        assert path.read_text(encoding="utf-8") == original
        # No leftover temp file either.
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_write_uses_os_replace_and_cleans_up_temp_file(self, tmp_path, monkeypatch):
        path = tmp_path / "skills.json"
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)
        calls = []
        real_replace = sr.os.replace

        def _spy_replace(src, dst):
            calls.append(Path(src).name)
            return real_replace(src, dst)

        monkeypatch.setattr(sr.os, "replace", _spy_replace)
        sr.write_registry({"skills": {}})

        assert len(calls) == 1
        tmp_name = calls[0]
        assert tmp_name != path.name  # written to a distinct temp file first
        # After a successful swap, only the final file remains.
        assert [p.name for p in path.parent.iterdir()] == [path.name]

    def test_replace_failure_cleans_up_temp_file(self, tmp_path, monkeypatch):
        path = tmp_path / "skills.json"
        monkeypatch.setattr(sr, "REGISTRY_PATH", path)

        def _boom_replace(src, dst):
            raise OSError("disk full")

        monkeypatch.setattr(sr.os, "replace", _boom_replace)
        with pytest.raises(OSError):
            sr.write_registry({"skills": {}})

        # The failed swap must not leave the temp file behind, and the
        # target was never created.
        assert list(path.parent.iterdir()) == []


# ---------------------------------------------------------------------------
# Staleness cache
# ---------------------------------------------------------------------------


class TestStalenessCache:
    def test_missing_cache_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", tmp_path / "skills-check.json")
        assert sr.read_staleness_cache() is None

    def test_fresh_cache_returns_results(self, tmp_path, monkeypatch):
        path = tmp_path / "skills-check.json"
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", path)
        sr.write_staleness_cache({"foo": "1.0.0"})
        cache = sr.read_staleness_cache()
        assert cache is not None
        assert cache["results"] == {"foo": "1.0.0"}

    def test_stale_cache_returns_none(self, tmp_path, monkeypatch):
        path = tmp_path / "skills-check.json"
        path.write_text(
            json.dumps({"checked_at": time.time() - sr.STALENESS_TTL_SECONDS - 1, "results": {"foo": "1.0.0"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", path)
        assert sr.read_staleness_cache() is None

    def test_corrupt_cache_returns_none(self, tmp_path, monkeypatch):
        path = tmp_path / "skills-check.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", path)
        assert sr.read_staleness_cache() is None

    # -- W4: failure-stamp backoff --

    def test_write_staleness_failure_then_read_within_window(self, tmp_path, monkeypatch):
        path = tmp_path / "skills-check.json"
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", path)
        sr.write_staleness_failure()
        cache = sr.read_staleness_cache()
        assert cache is not None
        assert cache["failed"] is True

    def test_failure_stamp_expires_after_backoff_window(self, tmp_path, monkeypatch):
        path = tmp_path / "skills-check.json"
        path.write_text(
            json.dumps({"checked_at": time.time() - sr.STALENESS_FAILURE_TTL_SECONDS - 1, "failed": True}),
            encoding="utf-8",
        )
        monkeypatch.setattr(sr, "STALENESS_CACHE_PATH", path)
        assert sr.read_staleness_cache() is None

    def test_failure_stamp_backoff_is_shorter_than_success_ttl(self):
        # The whole point of the failure stamp: back off for less time than
        # a successful check is trusted for, so the network gets retried
        # again reasonably soon rather than waiting a full day.
        assert sr.STALENESS_FAILURE_TTL_SECONDS < sr.STALENESS_TTL_SECONDS
