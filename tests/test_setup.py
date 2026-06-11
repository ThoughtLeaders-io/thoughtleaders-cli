"""Tests for `tl setup` helpers."""

import sys
from pathlib import Path

from tl_cli.commands import setup
from tl_cli.commands.setup import (
    _bundled_skill_blurbs,
    _find_claude_binary,
    _install_command_shim,
    _remove_matching_standalone_skills,
    _trees_identical,
)


def _write_skill(skills_dir: Path, name: str, body: str) -> None:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(body, encoding="utf-8")


class TestBundledSkillBlurbs:
    def test_reads_name_and_blurb_sorted(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "tl", "---\nname: tl\ntl-blurb: data analyst\ndescription: |\n  Long desc.\n---\n")
        _write_skill(skills, "alpha", "---\nname: alpha\ntl-blurb: first thing\ndescription: x\n---\n")
        assert _bundled_skill_blurbs(tmp_path) == [
            ("alpha", "first thing"),
            ("tl", "data analyst"),
        ]

    def test_skips_skill_without_blurb(self, tmp_path):
        skills = tmp_path / "skills"
        _write_skill(skills, "tl", "---\nname: tl\ntl-blurb: has one\ndescription: x\n---\n")
        _write_skill(skills, "other", "---\nname: other\ndescription: no blurb here\n---\n")
        assert _bundled_skill_blurbs(tmp_path) == [("tl", "has one")]

    def test_ignores_blurb_lookalike_in_body(self, tmp_path):
        # A `tl-blurb:` line in the markdown body (after frontmatter) must not be picked up.
        skills = tmp_path / "skills"
        _write_skill(
            skills,
            "tl",
            "---\nname: tl\ntl-blurb: real blurb\ndescription: x\n---\n\ntl-blurb: not this one\n",
        )
        assert _bundled_skill_blurbs(tmp_path) == [("tl", "real blurb")]

    def test_missing_skills_dir_returns_empty(self, tmp_path):
        assert _bundled_skill_blurbs(tmp_path) == []


class TestTreesIdentical:
    def test_identical_trees(self, tmp_path):
        for root in ("a", "b"):
            d = tmp_path / root / "sub"
            d.mkdir(parents=True)
            (d / "f.md").write_text("same", encoding="utf-8")
        assert _trees_identical(tmp_path / "a", tmp_path / "b")

    def test_different_content(self, tmp_path):
        for root, body in (("a", "one"), ("b", "two")):
            d = tmp_path / root
            d.mkdir()
            (d / "f.md").write_text(body, encoding="utf-8")
        assert not _trees_identical(tmp_path / "a", tmp_path / "b")

    def test_ignores_pycache_artifacts(self, tmp_path):
        for root in ("a", "b"):
            d = tmp_path / root / "scripts"
            d.mkdir(parents=True)
            (d / "run.py").write_text("print()", encoding="utf-8")
        cache = tmp_path / "b" / "scripts" / "__pycache__"
        cache.mkdir()
        (cache / "run.cpython-313.pyc").write_text("bytecode", encoding="utf-8")
        assert _trees_identical(tmp_path / "a", tmp_path / "b")

    def test_extra_file(self, tmp_path):
        for root in ("a", "b"):
            d = tmp_path / root
            d.mkdir()
            (d / "f.md").write_text("same", encoding="utf-8")
        (tmp_path / "b" / "extra.md").write_text("x", encoding="utf-8")
        assert not _trees_identical(tmp_path / "a", tmp_path / "b")


class TestRemoveMatchingStandaloneSkills:
    def _plugin_with_skill(self, root: Path, name: str, body: str) -> Path:
        skill = root / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(body, encoding="utf-8")
        return skill

    def test_removes_identical_copy(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        self._plugin_with_skill(plugin_root, "tl", "---\nname: tl\n---\n")
        standalone = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", standalone)
        copy = standalone / "tl"
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text("---\nname: tl\n---\n", encoding="utf-8")

        assert _remove_matching_standalone_skills(plugin_root) == (1, 0)
        assert not copy.exists()

    def test_keeps_modified_copy(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        self._plugin_with_skill(plugin_root, "tl", "---\nname: tl\n---\n")
        standalone = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", standalone)
        copy = standalone / "tl"
        copy.mkdir(parents=True)
        (copy / "SKILL.md").write_text("---\nname: tl\n---\nuser edit\n", encoding="utf-8")

        assert _remove_matching_standalone_skills(plugin_root) == (0, 1)
        assert copy.exists()

    def test_ignores_unrelated_personal_skills(self, tmp_path, monkeypatch):
        plugin_root = tmp_path / "plugin"
        self._plugin_with_skill(plugin_root, "tl", "---\nname: tl\n---\n")
        standalone = tmp_path / "claude-skills"
        monkeypatch.setattr(setup, "CLAUDE_SKILLS_DIR", standalone)
        other = standalone / "my-own-skill"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("mine", encoding="utf-8")

        assert _remove_matching_standalone_skills(plugin_root) == (0, 0)
        assert other.exists()


class TestInstallCommandShim:
    def test_writes_shim_pointing_at_plugin_skill(self, tmp_path, monkeypatch):
        monkeypatch.setattr(setup, "CLAUDE_COMMANDS_DIR", tmp_path / "commands")
        dst = _install_command_shim()
        assert dst == tmp_path / "commands" / "tl.md"
        body = dst.read_text(encoding="utf-8")
        assert "tl-cli:tl" in body
        assert "$ARGUMENTS" in body


class TestFindClaudeBinary:
    def test_prefers_execpath_env(self, tmp_path, monkeypatch):
        exe = tmp_path / "claude.exe"
        exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(exe))
        assert _find_claude_binary() == str(exe)

    def test_ignores_stale_execpath_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", str(tmp_path / "gone.exe"))
        monkeypatch.setattr(setup.shutil, "which", lambda _: "/somewhere/claude")
        assert _find_claude_binary() == "/somewhere/claude"

    def test_prefers_path(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        monkeypatch.setattr(setup.shutil, "which", lambda _: "/somewhere/claude")
        assert _find_claude_binary() == "/somewhere/claude"

    def test_finds_newest_desktop_app_binary(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        monkeypatch.setattr(setup.shutil, "which", lambda _: None)
        monkeypatch.setattr(setup.Path, "home", staticmethod(lambda: tmp_path))
        if sys.platform == "win32":
            base = tmp_path / "AppData" / "Roaming" / "Claude" / "claude-code"
            monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
            exe = "claude.exe"
        elif sys.platform == "darwin":
            base = tmp_path / "Library" / "Application Support" / "Claude" / "claude-code"
            exe = "claude"
        else:
            base = tmp_path / ".config" / "Claude" / "claude-code"
            exe = "claude"
        for version in ("2.1.165", "2.1.170"):
            d = base / version
            d.mkdir(parents=True)
            (d / exe).write_text("", encoding="utf-8")
        assert _find_claude_binary() == str(base / "2.1.170" / exe)

    def test_falls_back_to_local_bin(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        monkeypatch.setattr(setup.shutil, "which", lambda _: None)
        monkeypatch.setattr(setup.Path, "home", staticmethod(lambda: tmp_path))
        exe = "claude.exe" if sys.platform == "win32" else "claude"
        target = tmp_path / ".local" / "bin" / exe
        target.parent.mkdir(parents=True)
        target.write_text("", encoding="utf-8")
        assert _find_claude_binary() == str(target)

    def test_not_found_anywhere(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        monkeypatch.setattr(setup.shutil, "which", lambda _: None)
        monkeypatch.setattr(setup.Path, "home", staticmethod(lambda: tmp_path))
        if sys.platform == "win32":
            monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
        assert _find_claude_binary() is None
