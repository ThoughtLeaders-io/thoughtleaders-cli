"""Tests for the tl setup skill-sync helper."""

import shutil
from pathlib import Path

from tl_cli.commands.setup import (
    SKILLS_MANIFEST_FILENAME,
    _read_skills_manifest,
    _sync_plugin_skills,
)


def _make_skill(plugin_root: Path, name: str) -> None:
    skill_dir = plugin_root / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(f"---\nname: {name}\n---\n# {name}\n")


class TestSyncPluginSkills:
    def test_initial_install(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin"
        target = tmp_path / "target"
        _make_skill(plugin_root, "foo")
        _make_skill(plugin_root, "bar")

        count, swept = _sync_plugin_skills(plugin_root, target)

        assert count == 2
        assert swept == []
        assert (target / "foo" / "SKILL.md").is_file()
        assert (target / "bar" / "SKILL.md").is_file()
        assert _read_skills_manifest(target) == {"foo", "bar"}

    def test_sweeps_renamed_skill(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin"
        target = tmp_path / "target"

        # First install: foo + bar
        _make_skill(plugin_root, "foo")
        _make_skill(plugin_root, "bar")
        _sync_plugin_skills(plugin_root, target)
        assert (target / "foo" / "SKILL.md").is_file()

        # Rename: foo -> tl-foo in the source
        shutil.rmtree(plugin_root / "skills" / "foo")
        _make_skill(plugin_root, "tl-foo")

        count, swept = _sync_plugin_skills(plugin_root, target)

        assert count == 2  # bar + tl-foo
        assert swept == ["foo"]
        assert (target / "tl-foo" / "SKILL.md").is_file()
        assert (target / "bar" / "SKILL.md").is_file()
        assert not (target / "foo").exists()
        assert _read_skills_manifest(target) == {"bar", "tl-foo"}

    def test_never_touches_skills_outside_manifest(self, tmp_path: Path) -> None:
        """Critical invariant: sweep only removes skills this plugin installed.

        A user might install their own skill or a different tool's skill into
        the same target directory. The sweep must leave those alone.
        """
        plugin_root = tmp_path / "plugin"
        target = tmp_path / "target"
        _make_skill(plugin_root, "foo")
        # First install creates the manifest with just {foo}
        _sync_plugin_skills(plugin_root, target)

        # User drops in their own skill (NOT installed by this plugin)
        user_skill = target / "user-thing"
        user_skill.mkdir()
        (user_skill / "SKILL.md").write_text("user content")

        # Re-run sync — user-thing must survive even though it's not in the
        # source or the manifest. It wasn't installed by us, so we don't touch it.
        count, swept = _sync_plugin_skills(plugin_root, target)

        assert count == 1  # only foo from source
        assert swept == []
        assert (target / "user-thing" / "SKILL.md").is_file()
        assert (target / "user-thing" / "SKILL.md").read_text() == "user content"

    def test_no_manifest_on_first_install_is_fine(self, tmp_path: Path) -> None:
        """If the target dir already has some content from a pre-manifest
        install, the first run with manifest support won't sweep them — we
        haven't recorded them as ours yet. This is correct: we only sweep
        what we know we installed."""
        plugin_root = tmp_path / "plugin"
        target = tmp_path / "target"
        target.mkdir()
        # Simulate a pre-manifest leftover
        pre_existing = target / "old-skill"
        pre_existing.mkdir()
        (pre_existing / "SKILL.md").write_text("legacy")

        _make_skill(plugin_root, "new-skill")
        count, swept = _sync_plugin_skills(plugin_root, target)

        # First install — no manifest to compare against, so nothing swept.
        # `old-skill` survives this run; the *next* re-install (after a rename
        # in the source) will catch the renamed dir but `old-skill` stays
        # untouched permanently since we never claimed ownership.
        assert count == 1
        assert swept == []
        assert (target / "old-skill" / "SKILL.md").is_file()
        assert (target / "new-skill" / "SKILL.md").is_file()

    def test_empty_plugin_source(self, tmp_path: Path) -> None:
        plugin_root = tmp_path / "plugin"
        plugin_root.mkdir()
        target = tmp_path / "target"

        count, swept = _sync_plugin_skills(plugin_root, target)

        assert count == 0
        assert swept == []

    def test_skill_without_SKILL_md_is_ignored(self, tmp_path: Path) -> None:
        """Directories under `skills/` without a SKILL.md aren't real skills
        and shouldn't be copied or tracked."""
        plugin_root = tmp_path / "plugin"
        target = tmp_path / "target"
        (plugin_root / "skills" / "real").mkdir(parents=True)
        (plugin_root / "skills" / "real" / "SKILL.md").write_text("# real")
        (plugin_root / "skills" / "not-a-skill").mkdir()  # no SKILL.md

        count, swept = _sync_plugin_skills(plugin_root, target)

        assert count == 1
        assert swept == []
        assert (target / "real" / "SKILL.md").is_file()
        assert not (target / "not-a-skill").exists()
