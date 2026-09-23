#!/usr/bin/env python3
"""The run's opening, as one command instead of five turns.

Resolve, plan gate, channel context, reuse check and (when the host names are
already known) the fetch and the context stats. None of these has judgment
between it and the next: the plan gate and the brand resolution depend on
nothing, the identity read and the reuse check and the fetch need only the
channel id, and the stats need only the fetched corpus. Every gap between
them was an orchestrator turn, and a turn costs more than most of these
stages do.

**The one judgment in the opening is kept.** Host names are person-name
aliases chosen by reading the About text and generated profile. Brands,
companies, roles and topics are not host names: treating them as names turns
ordinary subject mentions into false second-speaker hints. The channel name
alone is not good enough: a channel called "Marta Builds" run with
``"Marta Builds,Marta"`` as its host names takes anchor soft mismatches on
every "builds". So with no ``--host-names`` this stops after the reuse check
and prints the identity it just read, and the caller picks the aliases and
runs the fetch in its next message. With ``--host-names`` there is nothing left to
decide and the whole opening, fetch and stats included, is one command.

The plan gate reports, it does not stop: ``plan`` and ``plan_ok`` are on the
summary and the rule stays where it was, with the caller.

Exit codes:
    0  ran to the end of what it could do; read ``decision`` and ``ran``
    3  a stage failed; its own error is on stderr
    4  a name did not resolve to one record. Candidates are on stdout and
       NOTHING else ran, so the caller asks once and calls again
    5  bad arguments

Usage:
    start_run.py --channel <ref> [--brand <ref>] [--host-names "a,b"]
                 [--reserve N] [--lanes transcripts+socials]
                 [--rebuild] [--no-refresh] [--profiles-dir DIR]
                 [--creator-brief | --no-creator-brief]
                 [--talking-points <path or text>] [--promoting "<line>"]

**The creator brief is an opt-in second file on a CONNECT run.** The user is
asked once, in the run's one wait turn, whether they want a version they can
send to the creator; on yes they are asked for the brand's baseline talking
points and what it is promoting, and that is the whole interview. A flag
skips a question, it never answers it silently. The answers are written
verbatim to ``<corpus>/creator-brief-input-<brand_id>.json`` (schema
``tl-creator-brief-input/v1``), so the brief writer reads the brand's own
words, never a paraphrase. ``--talking-points`` or
``--promoting`` implies ``--creator-brief``. None of these flags is valid
without ``--brand``, and the ledger build never reads them: the profile is
brand-blind.

Output (stdout): one JSON object. Every stage's FUNNEL line passes through on
stderr, as though it had been run by hand.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data

SCRIPTS = pathlib.Path(__file__).resolve().parent
PLAN_OK = ("Intelligence", "Superuser")
PLAN_GATE_TIMEOUT = 20      # macOS has no `timeout`, so the bound is here
FIND_TIMEOUT = 60
NUMERIC = re.compile(r"\d+")


def funnel(**fields) -> None:
    """One machine-parseable stage line for debugging (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def resolve(kind: str, ref: str) -> dict:
    """``{"id": N, "name": …}`` for one record, or ``{"candidates": [...]}``.

    Resolution belongs to the CLI: it already auto-picks a dominant candidate
    and returns the rest as candidates when it cannot. Never match a name in
    a query here.
    """
    ref = ref.strip()
    if NUMERIC.fullmatch(ref):
        return {"id": int(ref), "name": None, "resolved_by": "id"}
    try:
        proc = subprocess.run([tl_data.TL_BIN, kind, "find", ref, "--json"],
                              capture_output=True, text=True,
                              timeout=FIND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"candidates": [], "detail": f"tl {kind} find failed: {exc}"}
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = {}
    results = data.get("results") or []
    if proc.returncode == 0 and results and results[0].get("id") is not None:
        return {"id": int(results[0]["id"]), "name": results[0].get("name"),
                "resolved_by": f"tl {kind} find"}
    return {"candidates": results[:4],
            "detail": (data.get("detail") or proc.stderr.strip()
                       or f"no {kind[:-1]} matched {ref!r}")}


def plan_gate() -> dict:
    """Report the plan; never stop on it. SKILL.md's rule (Intelligence or
    Superuser proceeds, a known lower tier stops, an unrecognised value is
    named and continues) needs a judgment about which tiers are known, so it
    stays with the caller, which now reads the answer off this summary
    instead of spending a turn on `tl whoami`."""
    for _ in range(2):        # one retry, exactly as SKILL.md says
        try:
            proc = subprocess.run([tl_data.TL_BIN, "whoami", "--json"],
                                  capture_output=True, text=True,
                                  timeout=PLAN_GATE_TIMEOUT)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        try:
            org = (json.loads(proc.stdout) or {}).get("organization") or {}
        except ValueError:
            continue
        plan = org.get("plan")
        return {"plan": plan, "plan_ok": plan in PLAN_OK,
                "plan_note": (None if plan in PLAN_OK else
                              f"{plan!r} is not Intelligence or Superuser: "
                              f"apply the plan-gate rule before continuing")}
    return {"plan": None, "plan_ok": None,
            "plan_note": "plan gate: unreachable, continued"}


def run_script(name: str, args: list[str], *,
               stdout_to: pathlib.Path | None = None) -> tuple[int, str]:
    """A sibling script, run as its own process so its files, exit codes and
    FUNNEL line are exactly what they are when a person runs it. stderr is
    inherited, so the lines land in the run's own stderr in order."""
    cmd = [sys.executable, str(SCRIPTS / name), *args]
    if stdout_to is not None:
        stdout_to.parent.mkdir(parents=True, exist_ok=True)
        with stdout_to.open("w", encoding="utf-8") as fh:
            return subprocess.run(cmd, stdout=fh).returncode, ""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    return proc.returncode, proc.stdout


def read_check(stdout: str) -> tuple[str, dict]:
    """``ledger_meta.py check`` prints an announcement line for a found ledger
    and then its JSON. Keep both: the announcement is repeated to the user
    verbatim."""
    announcement, decision = "", {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                decision = json.loads(line)
                continue
            except ValueError:
                pass
        announcement = line
    return announcement, decision


def identity_block(context_full: pathlib.Path) -> dict:
    """What the host-names call is made from. The full file stays on disk; a
    caller that wants the rest opens it."""
    try:
        full = json.loads(context_full.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        "name": full.get("name"),
        "url": full.get("url"),
        "language": full.get("language"),
        "num_uploads": full.get("num_uploads"),
        "about_text": full.get("about_text"),
        "generated_profile": full.get("generated_profile"),
        "websites": [w.get("url") for w in (full.get("websites") or [])],
        "social_links": full.get("social_links") or [],
        "second_channel_candidates": full.get("second_channel_candidates") or [],
    }


CREATOR_BRIEF_INPUT_SCHEMA = "tl-creator-brief-input/v1"
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")


def read_lines(value: str | None) -> list[str]:
    """A path or literal text -> the brand's own lines, verbatim.

    A path that exists is read; anything else is the text itself. Lines are
    split on newlines, bullets and numbering stripped, blanks dropped. Nothing
    is reworded: what the brand wrote is what the brief writer sees.
    """
    if value is None:
        return []
    text = value
    candidate = pathlib.Path(value)
    try:
        if len(value) < 1024 and candidate.is_file():
            text = candidate.read_text(encoding="utf-8")
    except OSError:
        pass
    lines = [_BULLET.sub("", ln).strip() for ln in text.splitlines()]
    return [ln for ln in lines if ln]


def creator_brief_input(a, channel: dict, brand: dict) -> dict:
    """The verbatim input record for the creator brief writer."""
    points = read_lines(a.talking_points)
    return {
        "schema": CREATOR_BRIEF_INPUT_SCHEMA,
        "channel_id": channel["id"],
        "channel_name": channel.get("name"),
        "brand_id": brand["id"],
        "brand_name": brand.get("name"),
        "promoting": (a.promoting or "").strip() or None,
        "talking_points": points,
        # supplied: the brand said what it wants; False means the brief is
        # built from the connection map alone and its header says so
        "supplied": bool(points or (a.promoting or "").strip()),
        "written_at": time.strftime("%Y-%m-%d"),
    }


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", required=True,
                    help="URL, @handle, YouTube id, numeric TL id, or a name")
    ap.add_argument("--brand", default=None,
                    help="same forms; CONNECT only. Resolved before anything "
                         "runs, so an unresolvable brand costs no fetch")
    ap.add_argument("--host-names", dest="host_names", default=None,
                    help="person-name aliases for the host, e.g. 'Kate,Kate "
                         "Hayes'. Brands, companies, roles and topics are "
                         "invalid because these values drive speaker "
                         "attribution. Given, this runs the fetch and stats "
                         "too; omitted, it stops after the reuse check and "
                         "prints the identity to choose them from")
    ap.add_argument("--reserve", type=int, default=0,
                    help="agent slots held back from the extractor wave: 3 "
                         "for the brand lanes on a CONNECT build, plus 1 with "
                         "socials")
    ap.add_argument("--lanes", default=None,
                    choices=("transcripts", "transcripts+socials"))
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-refresh", dest="no_refresh", action="store_true")
    ap.add_argument("--profiles-dir", dest="profiles_dir",
                    default="tl-creator-profiles")
    cb = ap.add_mutually_exclusive_group()
    cb.add_argument("--creator-brief", dest="creator_brief", action="store_true",
                    default=None,
                    help="CONNECT only: also produce the creator-friendly brief. "
                         "Neither flag given, the run asks once")
    cb.add_argument("--no-creator-brief", dest="creator_brief", action="store_false",
                    help="CONNECT only: the internal connections page only")
    ap.add_argument("--talking-points", dest="talking_points", default=None,
                    help="the brand's baseline talking points, a file path or "
                         "the text itself, one point per line; implies "
                         "--creator-brief")
    ap.add_argument("--promoting", default=None,
                    help="one line on what the brand is promoting in this ad; "
                         "implies --creator-brief")
    a = ap.parse_args(argv)

    brief_inputs = [f for f, v in (("--talking-points", a.talking_points),
                                   ("--promoting", a.promoting)) if v]
    if (brief_inputs or a.creator_brief is not None) and not a.brand:
        print(json.dumps({"exit": 5, "error": "creator-brief inputs need --brand: "
                          + ", ".join(brief_inputs or ["--creator-brief"])}, indent=1))
        return 5
    if a.creator_brief is False and (a.talking_points or a.promoting):
        print(json.dumps({"exit": 5, "error": "--no-creator-brief contradicts "
                          + " and ".join(f for f in brief_inputs
                                         if f in ("--talking-points", "--promoting"))},
                         indent=1))
        return 5
    if a.creator_brief is None and (a.talking_points or a.promoting):
        a.creator_brief = True

    out: dict = {"ran": []}

    channel = resolve("channels", a.channel)
    if "id" not in channel:
        print(json.dumps({"exit": 4, "ask": "channel", **channel}, indent=1))
        return 4
    out["channel"] = channel
    if a.brand:
        brand = resolve("brands", a.brand)
        if "id" not in brand:
            print(json.dumps({"exit": 4, "ask": "brand", **brand,
                              "channel": channel}, indent=1))
            return 4
        out["brand"] = brand
    out["ran"].append("resolve")

    out.update(plan_gate())
    out["ran"].append("plan_gate")

    cid = channel["id"]
    profiles = pathlib.Path(a.profiles_dir)
    corpus = profiles / ".corpus" / str(cid)
    context_full = corpus / "context-full.json"

    # the creator brief's inputs are written before anything that can fail,
    # verbatim, so a re-run after a failed stage does not ask for them twice
    out["creator_brief"] = ({True: "on", False: "off"}.get(a.creator_brief, "ask")
                            if a.brand else None)
    out["creator_brief_input"] = None
    out["talking_points"] = 0
    if a.brand and (a.creator_brief or brief_inputs):
        record = creator_brief_input(a, channel, out["brand"])
        input_path = corpus / f"creator-brief-input-{out['brand']['id']}.json"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")
        out["creator_brief_input"] = str(input_path)
        out["talking_points"] = len(record["talking_points"])
        out["ran"].append("creator_brief_input")

    rc, _ = run_script("channel_context.py", ["--channel", str(cid)],
                       stdout_to=context_full)
    if rc != 0:
        print(json.dumps({**out, "exit": 3, "failed": "channel_context"}, indent=1))
        return 3
    out["context_full"] = str(context_full)
    out["identity"] = identity_block(context_full)
    out["ran"].append("channel_context")

    check_args = ["check", "--channel", str(cid), "--profiles-dir", str(profiles)]
    if a.lanes:
        check_args += ["--lanes", a.lanes]
    if a.rebuild:
        check_args.append("--rebuild")
    if a.no_refresh:
        check_args.append("--no-refresh")
    rc, stdout = run_script("ledger_meta.py", check_args)
    if rc != 0:
        print(json.dumps({**out, "exit": 3, "failed": "ledger_meta check"}, indent=1))
        return 3
    announcement, check = read_check(stdout)
    out["announcement"] = announcement
    out["check"] = check
    out["decision"] = check.get("decision")
    out["ran"].append("reuse_check")

    if out["decision"] == "reuse":
        out["next"] = ("reuse: PROFILE reports the ledger as it is, CONNECT "
                       "goes straight to the brand read. No fetch.")
    elif a.host_names is None:
        out["next"] = ("host names are the one call in the opening: read "
                       "`identity` above, then run fetch_cues.py with them "
                       "(and the context stats) in your next message. Pass "
                       "--host-names to have this command do both.")
    else:
        fetch_args = ["--channel", str(cid), "--host-names", a.host_names,
                      "--reserve", str(a.reserve),
                      "--out", str(profiles / ".corpus")]
        if out["decision"] == "refresh":
            # bounded to the uploads the ledger has not seen, so the round
            # costs what the new videos cost and not what the catalogue does
            fetch_args += ["--round", str(check.get("next_round") or 2)]
            if check.get("latest_video_date"):
                fetch_args += ["--since", str(check["latest_video_date"])]
            classified = corpus / "classified.jsonl"
            if classified.exists():
                fetch_args += ["--exclude", str(classified)]
        rc, stdout = run_script("fetch_cues.py", fetch_args)
        if rc != 0:
            print(json.dumps({**out, "exit": 3, "failed": "fetch_cues"}, indent=1))
            return 3
        try:
            out["fetch"] = json.loads(stdout)
        except ValueError:
            out["fetch"] = {"stdout": stdout[-2000:]}
        out["ran"].append("fetch")

        rc, _ = run_script(
            "channel_context.py",
            ["--channel", str(cid), "--corpus", str(corpus / "corpus.jsonl.gz"),
             "--per-video-out", str(corpus / "per-video.jsonl")],
            stdout_to=context_full)
        if rc != 0:
            print(json.dumps({**out, "exit": 3, "failed": "context stats"}, indent=1))
            return 3
        out["ran"].append("context_stats")
        out["next"] = ("call the format from the `FUNNEL stage=context` line "
                       "above, then write the context block and render the "
                       "batch prompts in one chain (PROFILE step 2).")

    out["exit"] = 0
    print(json.dumps(out, indent=1, default=str))
    funnel(stage="start_run", channel=cid,
           brand=(out.get("brand") or {}).get("id"),
           decision=out["decision"], stages=len(out["ran"]),
           elapsed_s=round(time.monotonic() - t0, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
