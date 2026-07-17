"""Tests for setup.py's respect of `.tl-skill.json`-marked skill directories.

Encodes the P9 rule: a directory downloaded via `tl skill download` must
survive `tl setup` / `tl update` re-syncs untouched, even when its name
collides with a bundled skill and even when its content happens to be
byte-identical to the bundled version. Unmarked (or corrupt-marker) dirs
keep the pre-existing behaviour — installed/refreshed or removed as before.
"""

from pathlib import Path

import pytest

from tl_cli.commands import setup
from tl_cli.commands.setup import (
    _install_skill_trees,
    _install_standalone_skills,
    _remove_matching_standalone_skills,
)
from tl_cli.skill_registry import install_skill_tree


def _write_bundled_skill(plugin_root: Path, name: str, body: str) -> Path:
    skill_dir = plugin_root / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")
    return skill_dir


class TestInstallSkillTreesRespectsMarker:
    def test_marked_dir_survives_and_sibling_still_installs(self, tmp_path, capsys):
        plugin_root = tmp_path / "plugin"
        _write_bundled_skill(plugin_root, "foo", "# bundled foo")
        _write_bundled_skill(plugin_root, "bar", "# bundled bar")

        target_dir = tmp_path / "agents" / "skills"
        marked = target_dir / "foo"
        install_skill_tree({"SKILL.md": "# downloaded foo"}, marked, name="foo", version="1.2.3", checksum="abc")
        before = (marked / "SKILL.md").read_text(encoding="utf-8")

        count = _install_skill_trees(plugin_root, target_dir)

        # foo untouched (content + marker survive byte-for-byte); bar installed.
        assert (marked / "SKILL.md").read_text(encoding="utf-8") == before
        assert (marked / ".tl-skill.json").exists()
        assert (target_dir / "bar" / "SKILL.md").read_text(encoding="utf-8") == "# bundled bar"
        assert count == 1  # only bar counted — foo was skipped, not installed

        err = capsys.readouterr().err.replace("\n", "")
        assert "skipping" in err
        assert str(marked) in err
        assert "tl skill remove foo" in err

    def test_unmarked_dir_still_replaced(self, tmp_path):
        plugin_root = tmp_path / "plugin"
        _write_bundled_skill(plugin_root, "foo", "# bundled foo")

        target_dir = tmp_path / "agents" / "skills"
        unmarked = target_dir / "foo"
        unmarked.mkdir(parents=True)
        (unmarked / "SKILL.md").write_text("old content", encoding="utf-8")

        count = _install_skill_trees(plugin_root, target_dir)

        assert count == 1
        assert (unmarked / "SKILL.md").read_text(encoding="utf-8") == "# bundled foo"

    def test_version_stamp_written_even_when_a_skill_is_skipped(self, tmp_path):
        plugin_root = tmp_path / "plugin"
        _write_bundled_skill(plugin_root, "foo", "# bundled foo")

        target_dir = tmp_path / "agents" / "skills"
        marked = target_dir / "foo"
        install_skill_tree({"SKILL.md": "# downloaded"}, marked, name="foo", version="1.0.0", checksum="c")

        _install_skill_trees(plugin_root, target_dir)

        assert (target_dir / ".tl-version").read_text() == setup.__version__


class TestInstallStandaloneSkillsRespectsMarker:
    def test_marked_dir_survives_and_sibling_still_installs(self, tmp_path, monkeypatch, capsys):
        plugin_root = tmp_path / "plugin"
        _write_bundled_skill(plugin_root, "foo", "# bundled foo")
        _write_bundled_skill(plugin_root, "bar", "# bundled bar")

        claude_skills = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", claude_skills)

        marked = claude_skills / "foo"
        install_skill_tree({"SKILL.md": "# downloaded foo"}, marked, name="foo", version="1.2.3", checksum="abc")

        count = _install_standalone_skills(plugin_root)

        assert (marked / "SKILL.md").read_text(encoding="utf-8") == "# downloaded foo"
        assert (claude_skills / "bar" / "SKILL.md").read_text(encoding="utf-8") == "# bundled bar"
        assert count == 1  # bar only

        err = capsys.readouterr().err.replace("\n", "")
        assert "skipping" in err
        assert "tl skill remove foo" in err


class TestRemoveMatchingStandaloneSkillsRespectsMarker:
    def test_marked_identical_copy_is_not_deleted(self, tmp_path, monkeypatch, capsys):
        plugin_root = tmp_path / "plugin"
        body = "---\nname: tl\n---\n"
        _write_bundled_skill(plugin_root, "tl", body)

        claude_skills = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", claude_skills)
        marked = claude_skills / "tl"
        # Byte-identical to the bundled skill, but tl-managed (marker present).
        install_skill_tree({"SKILL.md": body}, marked, name="tl", version="1.0.0", checksum="c")

        removed, kept = _remove_matching_standalone_skills(plugin_root)

        assert removed == 0
        assert kept == 0  # not "kept as modified" either — it's simply not a candidate
        assert marked.exists()
        assert (marked / ".tl-skill.json").exists()

        err = capsys.readouterr().err.replace("\n", "")
        assert "skipping" in err
        assert "tl skill remove tl" in err

    def test_unmarked_identical_copy_still_deleted(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        body = "---\nname: tl\n---\n"
        _write_bundled_skill(plugin_root, "tl", body)

        claude_skills = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", claude_skills)
        copy = claude_skills / "tl"
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text(body, encoding="utf-8")

        removed, kept = _remove_matching_standalone_skills(plugin_root)

        assert removed == 1
        assert kept == 0
        assert not copy.exists()


class TestCorruptMarkerIsTreatedAsUnmanaged:
    def test_corrupt_marker_file_does_not_block_install_skill_trees(self, tmp_path):
        plugin_root = tmp_path / "plugin"
        _write_bundled_skill(plugin_root, "foo", "# bundled foo")

        target_dir = tmp_path / "agents" / "skills"
        dest = target_dir / "foo"
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text("old", encoding="utf-8")
        (dest / ".tl-skill.json").write_text("{not json", encoding="utf-8")

        count = _install_skill_trees(plugin_root, target_dir)

        assert count == 1
        assert (dest / "SKILL.md").read_text(encoding="utf-8") == "# bundled foo"

    def test_corrupt_marker_file_falls_through_to_tree_comparison(self, tmp_path, monkeypatch, capsys):
        """A corrupt `.tl-skill.json` is not a valid marker, so `is_marked_for`
        is False and the directory is NOT excluded via the marker-skip path
        (no warning printed) — it falls through to the pre-existing
        byte-comparison logic instead. The stray marker file itself is an
        extra file `_trees_identical` doesn't ignore, so the tree no longer
        matches the bundled skill and the old code correctly keeps it
        (as "modified"), rather than deleting or silently excluding it.
        """
        plugin_root = tmp_path / "plugin"
        body = "---\nname: tl\n---\n"
        _write_bundled_skill(plugin_root, "tl", body)

        claude_skills = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", claude_skills)
        copy = claude_skills / "tl"
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text(body, encoding="utf-8")
        (copy / ".tl-skill.json").write_text("{not json", encoding="utf-8")

        removed, kept = _remove_matching_standalone_skills(plugin_root)

        assert removed == 0
        assert kept == 1  # old "modified copy" behavior, not the marker-skip path
        assert copy.exists()
        assert "skipping" not in capsys.readouterr().err


class TestResyncIntegrationsHasNoDirectFileOps:
    def test_resync_shells_out_to_tl_setup_only(self):
        """`_resync_integrations` (self_update.py) re-syncs by spawning `tl setup
        <tool> --json` subprocesses — it never touches skill directories itself,
        so the marker-respect fix in setup.py's `_install_skill_trees` /
        `_install_standalone_skills` covers it without any change needed here."""
        import inspect

        from tl_cli.self_update import _resync_integrations

        src = inspect.getsource(_resync_integrations)
        assert "rmtree" not in src
        assert "copytree" not in src
        assert "setup" in src  # confirms it delegates via `tl setup <tool>`


@pytest.mark.parametrize("fn", [_install_skill_trees])
def test_marker_skip_does_not_raise(tmp_path, fn):
    """A skip must not raise or abort the loop — sanity guard against a
    regression that would turn `continue` into an exception path."""
    plugin_root = tmp_path / "plugin"
    _write_bundled_skill(plugin_root, "foo", "# bundled foo")
    target_dir = tmp_path / "target"
    marked = target_dir / "foo"
    install_skill_tree({"SKILL.md": "x"}, marked, name="foo", version="1.0.0", checksum="c")
    fn(plugin_root, target_dir)  # must not raise
