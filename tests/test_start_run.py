"""start_run.py: the run's opening as one command.

Hermetic. The `tl` binary is a stub selected through tl_data.TL_BIN (the
pattern in test_shared_tl_data.py) and the sibling scripts are stubs in a
temp SCRIPTS dir, so no network, no corpus and no ledger. What is asserted
is the wiring: what runs, in what order, with which flags, and what stops
before anything runs.
"""

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = (Path(__file__).resolve().parents[1]
            / "skills" / "tl-creator-brief" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "_shared"))
import tl_data  # noqa: E402
import start_run  # noqa: E402


# --------------------------------------------------------------------------- #
# stubs
# --------------------------------------------------------------------------- #
def _tl_stub(tmp_path: Path, responses: dict) -> Path:
    """A fake `tl`. ``responses`` maps the first argument ("whoami",
    "channels", "brands") to ``{"stdout": …, "exit": …}``."""
    script = tmp_path / "tl_stub.py"
    script.write_text(
        "import json, sys\n"
        f"responses = {json.dumps(responses)}\n"
        "r = responses.get(sys.argv[1], {})\n"
        "sys.stdout.write(r.get('stdout', ''))\n"
        "sys.stderr.write(r.get('stderr', ''))\n"
        "sys.exit(r.get('exit', 0))\n")
    runner = tmp_path / "tl"
    runner.write_text(f"#!/bin/sh\nexec {sys.executable} {script} \"$@\"\n")
    runner.chmod(0o755)
    return runner


_FAKE = """import json, pathlib, sys
pathlib.Path({log!r}).open("a").write(json.dumps(
    {{"script": {name!r}, "argv": sys.argv[1:]}}) + "\\n")
sys.stdout.write({stdout!r})
sys.exit({exit_code})
"""


def _script_stubs(tmp_path: Path, *, decision: dict, announcement: str = "",
                  fetch_exit: int = 0) -> tuple[Path, Path]:
    """A SCRIPTS dir of fakes. Returns (scripts_dir, call log)."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    log = tmp_path / "calls.jsonl"
    check_out = (f"{announcement}\n" if announcement else "") + json.dumps(decision)
    for name, stdout, code in (
        ("channel_context.py", json.dumps({
            "channel_id": 42, "name": "Airrack", "url": "https://y/@airrack",
            "language": "en", "num_uploads": 283,
            "about_text": "Eric Decker. Stunts.",
            "generated_profile": "large-scale stunt videos",
            "websites": [{"url": "https://airrack.com", "label": "site"}],
            "social_links": ["https://instagram.com/airrack"],
            "second_channel_candidates": [{"url": "https://y/@airrackplus"}],
        }), 0),
        ("ledger_meta.py", check_out, 0),
        ("fetch_cues.py", json.dumps({"windows": 500, "batch_size": 25}), fetch_exit),
    ):
        (scripts / name).write_text(_FAKE.format(
            log=str(log), name=name, stdout=stdout, exit_code=code))
    return scripts, log


def _calls(log: Path) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def _of(log: Path, name: str) -> list[list[str]]:
    return [c["argv"] for c in _calls(log) if c["script"] == name]


@pytest.fixture
def env(tmp_path, monkeypatch, capsys):
    """A run harness: stubs wired in, returns a callable that runs main()."""
    def _run(argv, *, decision=None, announcement="", tl=None, fetch_exit=0):
        scripts, log = _script_stubs(
            tmp_path,
            decision=decision or {"decision": "build", "reason": "no ledger",
                                  "next_round": 1},
            announcement=announcement, fetch_exit=fetch_exit)
        monkeypatch.setattr(start_run, "SCRIPTS", scripts)
        monkeypatch.setattr(tl_data, "TL_BIN", str(_tl_stub(tmp_path, tl or {
            "whoami": {"stdout": json.dumps(
                {"organization": {"plan": "Superuser"}})},
        })))
        rc = start_run.main(argv + ["--profiles-dir", str(tmp_path / "profiles")])
        out = capsys.readouterr().out
        return rc, json.loads(out), log
    return _run


# --------------------------------------------------------------------------- #
# the whole opening in one command
# --------------------------------------------------------------------------- #
def test_a_numeric_id_with_host_terms_runs_the_whole_opening(env):
    rc, out, log = env(["--channel", "42", "--host-terms", "Decker,Airrack",
                        "--reserve", "3"])
    assert rc == 0
    assert out["channel"] == {"id": 42, "name": None, "resolved_by": "id"}
    assert out["ran"] == ["resolve", "plan_gate", "channel_context",
                          "reuse_check", "fetch", "context_stats"]
    fetch = _of(log, "fetch_cues.py")[0]
    assert fetch[:6] == ["--channel", "42", "--host-terms", "Decker,Airrack",
                         "--reserve", "3"]
    # the identity read comes first and takes no corpus; the stats pass does
    identity, stats = _of(log, "channel_context.py")
    assert identity == ["--channel", "42"]
    assert "--corpus" in stats and "--per-video-out" in stats


def test_the_plan_is_reported_not_enforced(env):
    """SKILL.md's tier rule needs a judgment about which tiers are known, so
    the script reports and the caller decides. It never stops the run."""
    rc, out, _ = env(["--channel", "42"], tl={
        "whoami": {"stdout": json.dumps({"organization": {"plan": "Starter"}})}})
    assert rc == 0
    assert out["plan"] == "Starter" and out["plan_ok"] is False
    assert "not Intelligence or Superuser" in out["plan_note"]


def test_an_unreachable_plan_gate_continues_and_says_so(env):
    rc, out, log = env(["--channel", "42", "--host-terms", "x"],
                       tl={"whoami": {"stdout": "", "exit": 1}})
    assert rc == 0
    assert out["plan"] is None and out["plan_ok"] is None
    assert out["plan_note"] == "plan gate: unreachable, continued"
    assert _of(log, "fetch_cues.py"), "the gate must not block the run"


# --------------------------------------------------------------------------- #
# the one judgment in the opening is kept
# --------------------------------------------------------------------------- #
def test_without_host_terms_it_stops_and_hands_back_the_identity(env):
    """Host terms come from the About text and the profile: the channel name
    alone is what gave HopeScope 22 anchor soft mismatches. So this stage
    stops here rather than guessing."""
    rc, out, log = env(["--channel", "42"])
    assert rc == 0
    assert out["ran"] == ["resolve", "plan_gate", "channel_context", "reuse_check"]
    assert _of(log, "fetch_cues.py") == []
    assert out["identity"]["about_text"] == "Eric Decker. Stunts."
    assert out["identity"]["generated_profile"] == "large-scale stunt videos"
    assert out["identity"]["websites"] == ["https://airrack.com"]
    assert "host terms" in out["next"]


# --------------------------------------------------------------------------- #
# resolution: ask once, before anything runs
# --------------------------------------------------------------------------- #
def test_an_ambiguous_channel_name_asks_before_anything_runs(env):
    rc, out, log = env(["--channel", "Alexa"], tl={
        "channels": {"exit": 1, "stdout": json.dumps(
            {"detail": "Ambiguous match",
             "results": [{"id": 1, "name": "Alexa Rivera"},
                         {"id": 2, "name": "Alexa Sings"}]})},
        "whoami": {"stdout": json.dumps({"organization": {"plan": "Superuser"}})},
    })
    assert rc == 4
    assert out["ask"] == "channel"
    assert [c["name"] for c in out["candidates"]] == ["Alexa Rivera", "Alexa Sings"]
    assert _calls(log) == [], "nothing may run before the name is settled"


def test_an_unresolvable_brand_costs_no_fetch(env):
    rc, out, log = env(["--channel", "42", "--brand", "Liquid", "--host-terms", "x"],
                       tl={
        "brands": {"exit": 1, "stdout": json.dumps(
            {"detail": "Ambiguous match",
             "results": [{"id": 8787, "name": "Liquid I.V."},
                         {"id": 8788, "name": "Liquid Death"}]})},
        "whoami": {"stdout": json.dumps({"organization": {"plan": "Superuser"}})},
    })
    assert rc == 4 and out["ask"] == "brand"
    # the channel resolved, and is handed back so the re-ask does not redo it
    assert out["channel"]["id"] == 42
    assert _calls(log) == []


def test_a_resolved_name_is_reported_with_what_resolved_it(env):
    rc, out, _ = env(["--channel", "Airrack"], tl={
        "channels": {"stdout": json.dumps({"results": [{"id": 32402, "name": "Airrack"}]})},
        "whoami": {"stdout": json.dumps({"organization": {"plan": "Superuser"}})},
    })
    assert rc == 0
    assert out["channel"] == {"id": 32402, "name": "Airrack",
                              "resolved_by": "tl channels find"}


# --------------------------------------------------------------------------- #
# the reuse decision drives what runs next
# --------------------------------------------------------------------------- #
def test_reuse_runs_no_fetch_and_repeats_the_announcement(env):
    rc, out, log = env(
        ["--channel", "42", "--host-terms", "Decker"],
        announcement="Ledger built 2026-09-01 over 283 videos, 206 facts.",
        decision={"decision": "reuse", "reason": "2 new uploads <= 5",
                  "next_round": 3})
    assert rc == 0
    assert out["decision"] == "reuse"
    assert out["announcement"].startswith("Ledger built 2026-09-01")
    assert _of(log, "fetch_cues.py") == []
    assert out["ran"] == ["resolve", "plan_gate", "channel_context", "reuse_check"]


def test_a_refresh_bounds_the_fetch_to_what_the_ledger_has_not_seen(env, tmp_path):
    corpus = tmp_path / "profiles" / ".corpus" / "42"
    corpus.mkdir(parents=True)
    (corpus / "classified.jsonl").write_text("{}\n")
    rc, out, log = env(["--channel", "42", "--host-terms", "Decker"],
                       decision={"decision": "refresh", "reason": "29 new uploads > 5",
                                 "next_round": 2, "latest_video_date": "2026-08-20"})
    assert rc == 0
    fetch = _of(log, "fetch_cues.py")[0]
    assert fetch[fetch.index("--round") + 1] == "2"
    assert fetch[fetch.index("--since") + 1] == "2026-08-20"
    assert fetch[fetch.index("--exclude") + 1].endswith("classified.jsonl")


def test_a_first_build_asks_for_no_round_flags(env):
    rc, _, log = env(["--channel", "42", "--host-terms", "Decker"])
    fetch = _of(log, "fetch_cues.py")[0]
    assert "--round" not in fetch and "--since" not in fetch and "--exclude" not in fetch


def test_the_reuse_check_is_told_the_lanes_and_the_flags(env):
    rc, _, log = env(["--channel", "42", "--lanes", "transcripts+socials", "--rebuild"])
    check = _of(log, "ledger_meta.py")[0]
    assert check[0] == "check"
    assert check[check.index("--lanes") + 1] == "transcripts+socials"
    assert "--rebuild" in check


# --------------------------------------------------------------------------- #
# failures stop where they happen
# --------------------------------------------------------------------------- #
def test_a_failed_fetch_stops_the_chain_and_names_the_stage(env):
    rc, out, log = env(["--channel", "42", "--host-terms", "Decker"], fetch_exit=2)
    assert rc == 3
    assert out["failed"] == "fetch_cues"
    assert "context_stats" not in out["ran"]
