"""Context-size guards for the Claude Code plugin.

1. The SessionStart hook's output must stay small. Claude Code replaces hook
   output above its size cap with a ~2 KB "output too large" preview, so a
   large dump (the hook used to print the whole 70 KB tl SKILL.md) never
   reaches the model. 1.5 KB leaves a margin under that preview size.
2. Skill descriptions are loaded into every session's skill list, so they
   must stay short: 400 characters, keeping the trigger phrases.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "scripts" / "load-tl-skill.mjs"
MAX_HOOK_BYTES = 1536
MAX_DESCRIPTION_CHARS = 400

# Skills that predate the 400-character rule. Each may not grow past its
# current length; trim it and drop it from this list when someone next edits
# it. Every other skill (including new ones) must meet the 400 limit.
LEGACY_DESCRIPTION_CEILINGS = {
    "connector-impact": 1335,
    "tl-brand-creator-connection": 1630,
    "tl-create-workflow": 1265,
    "tl-save-report": 405,
    "tl-top-partnerships": 672,
}

node = shutil.which("node")


def _run_hook(plugin_root):
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
    if plugin_root is not None:
        env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    return subprocess.run(
        [node, str(HOOK)], env=env, capture_output=True, timeout=10, stdin=subprocess.DEVNULL
    )


@pytest.mark.skipif(node is None, reason="node is not installed")
class TestSessionStartHook:
    def test_output_is_a_short_pointer_to_the_tl_skill(self):
        result = _run_hook(ROOT)
        assert result.returncode == 0
        out = result.stdout.decode("utf-8")
        assert 0 < len(result.stdout) <= MAX_HOOK_BYTES, len(result.stdout)
        assert "tl-cli:tl" in out
        # Must not be (part of) the skill file itself.
        assert "# ThoughtLeaders Data Analyst" not in out

    def test_silent_without_plugin_root(self):
        result = _run_hook(None)
        assert result.returncode == 0
        assert result.stdout == b""

    def test_silent_when_skill_is_missing(self, tmp_path):
        result = _run_hook(tmp_path)
        assert result.returncode == 0
        assert result.stdout == b""

    def test_hook_is_wired_to_session_start(self):
        hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        commands = [
            h["command"] for entry in hooks["hooks"]["SessionStart"] for h in entry["hooks"]
        ]
        assert any("load-tl-skill.mjs" in c for c in commands)


def _skill_descriptions():
    for skill_md in sorted((ROOT / "skills").glob("*/SKILL.md")):
        frontmatter = skill_md.read_text(encoding="utf-8").split("---", 2)[1]
        meta = yaml.safe_load(frontmatter)
        yield skill_md.parent.name, " ".join(str(meta["description"]).split())


@pytest.mark.parametrize("name,description", list(_skill_descriptions()))
def test_skill_description_length(name, description):
    limit = LEGACY_DESCRIPTION_CEILINGS.get(name, MAX_DESCRIPTION_CHARS)
    assert len(description) <= limit, (
        f"{name} description is {len(description)} chars (limit {limit}); "
        "trim it, keeping the trigger phrases"
    )


def test_legacy_ceilings_only_list_existing_long_skills():
    lengths = {name: len(desc) for name, desc in _skill_descriptions()}
    for name in LEGACY_DESCRIPTION_CEILINGS:
        assert name in lengths, f"{name} no longer exists; drop it from the list"
        assert lengths[name] > MAX_DESCRIPTION_CHARS, (
            f"{name} is now within {MAX_DESCRIPTION_CHARS} chars; drop it from the list"
        )
