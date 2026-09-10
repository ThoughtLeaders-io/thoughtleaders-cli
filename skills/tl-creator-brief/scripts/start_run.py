#!/usr/bin/env python3
"""The run's opening, as one command instead of five turns.

Resolve, plan gate, channel context, reuse check and (when the host terms are
already known) the fetch and the context stats. None of these has judgment
between it and the next: the plan gate and the brand resolution depend on
nothing, the identity read and the reuse check and the fetch need only the
channel id, and the stats need only the fetched corpus. Every gap between
them was an orchestrator turn, and a turn costs more than most of these
stages do.

**The one judgment in the opening is kept.** Host terms are chosen by reading
the About text and the generated profile, and the channel name alone is not
good enough: HopeScope ran with ``"HopeScope,Hope"`` and took 22 anchor soft
mismatches. So with no ``--host-terms`` this stops after the reuse check and
prints the identity it just read, and the caller picks the terms and runs the
fetch in its next message. With ``--host-terms`` there is nothing left to
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
    start_run.py --channel <ref> [--brand <ref>] [--host-terms "a,b"]
                 [--reserve N] [--lanes transcripts+socials]
                 [--rebuild] [--no-refresh] [--profiles-dir DIR]

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
    """What the host-terms call is made from. The full file stays on disk; a
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


def main(argv: list[str] | None = None) -> int:
    t0 = time.monotonic()
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", required=True,
                    help="URL, @handle, YouTube id, numeric TL id, or a name")
    ap.add_argument("--brand", default=None,
                    help="same forms; CONNECT only. Resolved before anything "
                         "runs, so an unresolvable brand costs no fetch")
    ap.add_argument("--host-terms", dest="host_terms", default=None,
                    help="surname, company, former role: the terms the fetch "
                         "anchors on. Given, this runs the fetch and the "
                         "stats too; omitted, it stops after the reuse check "
                         "and prints the identity to choose them from")
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
    a = ap.parse_args(argv)

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
    elif a.host_terms is None:
        out["next"] = ("host terms are the one call in the opening: read "
                       "`identity` above, then run fetch_cues.py with them "
                       "(and the context stats) in your next message. Pass "
                       "--host-terms to have this command do both.")
    else:
        fetch_args = ["--channel", str(cid), "--host-terms", a.host_terms,
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
