"""Tests for `tl setup` helpers."""

from pathlib import Path

from tl_cli.commands.setup import _bundled_skill_blurbs


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
