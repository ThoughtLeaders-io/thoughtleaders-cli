"""Tests for skills/tl-brand-creator-connection/scripts/cast_sheet.py: the
per-video cast sheet, from render to the stamped batches."""

import json
import sys
from pathlib import Path

_SCRIPTS = (Path(__file__).resolve().parent.parent
            / "skills" / "tl-brand-creator-connection" / "scripts")
sys.path.insert(0, str(_SCRIPTS))
import cast_sheet  # noqa: E402


def _intros(tmp_path: Path, n: int = 3) -> Path:
    rows = [{"id": f"7:v{i}", "video_id": f"v{i}", "title": f"video {i}",
             "published": f"2025-01-0{i + 1}", "language": "en", "format_hint": None,
             "intro": "hey guys it's Eric and today my friends and I",
             "description": ["FOLLOW MY FRIENDS:", "Gavin: @GroovyGavin"]}
            for i in range(n)]
    p = tmp_path / "intros.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return p


def _context_full(tmp_path: Path) -> Path:
    p = tmp_path / "context-full.json"
    p.write_text(json.dumps({"name": "Airrack", "about_text": "Pizza. " * 200,
                             "generated_profile": "Eric Decker makes stunt videos."}))
    return p


def _render(tmp_path, monkeypatch, per_agent=2, host_names="Eric"):
    argv = ["cast_sheet.py", "render", "--intros", str(_intros(tmp_path)),
            "--context-full", str(_context_full(tmp_path)), "--host-names", host_names,
            "--out-dir", str(tmp_path / "prompts"), "--returns-dir", str(tmp_path / "returns"),
            "--per-agent", str(per_agent)]
    monkeypatch.setattr(sys, "argv", argv)
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append((a, k)))
    rc = cast_sheet.main()
    monkeypatch.undo()
    out = json.loads([a[0] for a, k in lines if not k.get("file")][0])
    return rc, out


def test_render_writes_one_self_contained_message_per_sheet(tmp_path, monkeypatch):
    rc, out = _render(tmp_path, monkeypatch)
    assert rc == 0 and out["videos"] == 3 and out["sheets"] == 2
    msg = Path(out["prompts"][0]).read_text()
    assert "# Cast sheet" in msg                       # the rubric, inline
    assert '"channel_name": "Airrack"' in msg and '"host_names": [\n  "Eric"\n ]' in msg
    assert "untrusted data" in msg
    videos = json.loads(msg.split("=== VIDEOS")[1].split("\n", 1)[1].split("\n\n")[0])
    assert [v["i"] for v in videos] == [0, 1] and videos[0]["video_id"] == "v0"
    assert videos[0]["description"] == ["FOLLOW MY FRIENDS:", "Gavin: @GroovyGavin"]
    assert str(tmp_path / "returns" / "cast-000.json") in msg and "cast=000 videos=2" in msg
    manifest = json.loads(Path(out["manifest"]).read_text())
    assert manifest["sheets"]["001"]["video_ids"] == ["v2"]
    assert Path(out["manifest"]).name == "cast-sheets.json"
    second = Path(out["prompts"][1]).read_text()
    assert "cast=001 videos=1" in second
    # the about text is clipped so the sheet stays small
    assert len(json.loads(msg.split("=== CONTEXT ===")[1].split("=== VIDEOS")[0])["channel_about"]) == 500


def test_render_with_no_intros_writes_no_sheet(tmp_path, monkeypatch):
    (tmp_path / "intros.jsonl").write_text("")
    monkeypatch.setattr(sys, "argv", [
        "cast_sheet.py", "render", "--intros", str(tmp_path / "intros.jsonl"),
        "--context-full", str(_context_full(tmp_path)),
        "--out-dir", str(tmp_path / "prompts"), "--returns-dir", str(tmp_path / "returns")])
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append((a, k)))
    assert cast_sheet.main() == 0
    monkeypatch.undo()
    out = json.loads([a[0] for a, k in lines if not k.get("file")][0])
    assert out == {**out, "videos": 0, "sheets": 0, "prompts": []}


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def _window(video, text, **extra):
    w = {"id": f"7:{video}", "video_id": video, "start": 100, "title": "t", "published": "2025-01-01",
         "language": "en", "format_hint": None, "text": text, "host_anchor": False,
         "host_anchor_terms": [], "host_named_third_person": [], "second_voice_hint": None}
    w.update(extra)
    return w


def _setup(tmp_path, monkeypatch, *, returns: dict, windows: list, host_names="", existing=None):
    _render(tmp_path, monkeypatch, per_agent=2)
    rdir = tmp_path / "returns"
    for sheet, data in returns.items():
        (rdir / f"cast-{sheet}.json").write_text(json.dumps(data))
    bdir = tmp_path / "batches"
    bdir.mkdir()
    (bdir / "batch-000.json").write_text(json.dumps(windows))
    out = tmp_path / "cast.json"
    if existing is not None:
        out.write_text(json.dumps(existing))
    monkeypatch.setattr(sys, "argv", [
        "cast_sheet.py", "apply", "--sheets", str(tmp_path / "cast-sheets.json"),
        "--returns", str(rdir), "--batches", str(bdir), "--out", str(out),
        "--host-names", host_names])
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append((a, k)))
    rc = cast_sheet.main()
    monkeypatch.undo()
    summary = json.loads([a[0] for a, k in lines if not k.get("file")][0])
    funnel = next((a[0] for a, k in lines if k.get("file") and str(a[0]).startswith("FUNNEL stage=cast ")), "")
    return rc, summary, json.loads((bdir / "batch-000.json").read_text()), funnel


_SHEET0 = {"sheet": "000", "videos": [
    {"i": 0, "video_id": "v0", "format": "collab", "hosts": ["Eric"],
     "guests": [{"name": "Gavin", "aliases": ["groovygavin", "Gavin Reed"], "role": "friend"}],
     "evidence": "opening: my friends and I; description: Gavin"},
    {"i": 1, "video_id": "v1", "format": "solo", "hosts": ["Eric"], "guests": [], "evidence": "alone"}]}
_SHEET1 = {"sheet": "001", "videos": [
    {"i": 0, "video_id": "v2", "format": "staged", "hosts": ["host"], "guests": [], "evidence": "prank title"}]}


def test_apply_stamps_cast_guest_flags_and_shared_voice_hints(tmp_path, monkeypatch):
    windows = [
        _window("v0", "so Gavin tell me about your dad and i grew up right here"),
        _window("v0", "hi i'm Gavin and i grew up in ohio with my dad"),
        _window("v0", "hey guys it's Eric and i grew up poor", format_hint="reaction"),
        _window("v1", "and i grew up poor honestly"),
        _window("v2", "i got fired from my job at the bank"),
        _window("v9", "nobody judged this video"),
    ]
    rc, summary, wins, funnel = _setup(tmp_path, monkeypatch,
                                       returns={"000": _SHEET0, "001": _SHEET1}, windows=windows,
                                       host_names="Eric")
    assert rc == 0 and summary["judged"] == 3 and summary["expected"] == 3
    assert summary["with_guests"] == 1 and summary["formats"] == {"collab": 1, "solo": 1, "staged": 1}
    w0, w1, w2, w3, w4, w5 = wins
    assert w0["cast"] == {"format": "collab", "hosts": ["Eric"], "guests": ["Gavin"]}
    assert w0["guest_named"] == ["gavin"] and w0["guest_anchor"] == []
    assert w0["format_hint"] == "interview_or_collab"           # the sheet says shared voice
    assert w1["guest_anchor"] == ["gavin"] and w1["guest_named"] == []
    assert w2["format_hint"] == "reaction"                        # a title hint is kept
    assert w3["cast"]["format"] == "solo" and w3["format_hint"] is None
    assert w3["guest_anchor"] == [] and w3["guest_named"] == []
    assert w4["format_hint"] == "staged"
    assert "cast" not in w5 and "guest_named" not in w5           # no verdict, nothing stamped
    assert summary["shared_voice_hinted"] == 3 and summary["guest_anchor_windows"] == 1
    assert summary["guest_named_windows"] == 1 and summary["windows_stamped"] == 5
    # the fetch had host names, so the host flags are its business
    assert summary["host_flags_source"] == "fetch" and summary["host_names_from_cast"] == []
    assert w2["host_anchor"] is False
    cast = json.loads((tmp_path / "cast.json").read_text())
    assert set(cast) == {"v0", "v1", "v2"} and cast["v0"]["guests"][0]["aliases"] == ["groovygavin", "Gavin Reed"]
    assert "with_guests=1" in funnel and "guest_named=1" in funnel and "exit=0" in funnel


def test_apply_takes_the_host_name_from_the_sheets_when_the_fetch_had_none(tmp_path, monkeypatch):
    windows = [_window("v0", "hey guys it's Eric and i grew up poor"),
               _window("v1", "with Eric today and i moved across the country"),
               _window("v2", "i got fired from my job")]
    rc, summary, wins, _ = _setup(tmp_path, monkeypatch,
                                  returns={"000": _SHEET0, "001": _SHEET1}, windows=windows)
    assert rc == 0
    assert summary["host_names_from_cast"] == ["Eric"] and summary["host_flags_source"] == "cast"
    assert wins[0]["host_anchor"] is True and wins[0]["host_anchor_terms"] == [["eric", "self_named"]]
    assert wins[1]["host_anchor"] is False and wins[1]["host_named_third_person"] == ["eric"]
    assert wins[1]["second_voice_hint"].startswith("host named in the third person")
    assert summary["third_person_host_share"] == 0.33
    # `host` (unnamed) never becomes a name
    assert "Host" not in summary["host_names"]


def test_apply_exits_3_on_a_missing_sheet_and_keeps_what_came_back(tmp_path, monkeypatch):
    windows = [_window("v0", "x"), _window("v2", "y")]
    rc, summary, wins, funnel = _setup(tmp_path, monkeypatch, returns={"000": _SHEET0},
                                       windows=windows, host_names="Eric")
    assert rc == 3 and summary["missing_sheets"] == ["001"]
    respawn = json.loads((tmp_path / "cast-respawn.json").read_text())
    assert respawn["missing_sheets"] == {"001": ["v2"]}
    assert "cast" in wins[0] and "cast" not in wins[1]
    assert set(json.loads((tmp_path / "cast.json").read_text())) == {"v0", "v1"}
    assert "exit=3" in funnel


def test_apply_leaves_a_bad_verdict_unjudged_and_merges_an_earlier_round(tmp_path, monkeypatch):
    bad = {"sheet": "000", "videos": [
        {"i": 0, "video_id": "v0", "format": "podcast", "hosts": ["Eric"], "guests": []},
        {"i": 1, "video_id": "v1", "format": "solo", "hosts": ["Eric"],
         "guests": [{"name": "Ann", "role": "producer"}]},
        {"i": 2, "video_id": "v7", "format": "solo", "hosts": [], "guests": []}]}
    rc, summary, wins, _ = _setup(tmp_path, monkeypatch, returns={"000": bad, "001": _SHEET1},
                                  windows=[_window("v0", "x"), _window("v8", "old")],
                                  host_names="Eric",
                                  existing={"v8": {"format": "solo", "hosts": ["Eric"], "guests": [], "evidence": ""}})
    assert rc == 0 and summary["judged"] == 1 and summary["carried"] == 1
    probs = summary["problems"]["000"]
    assert any("v0: format 'podcast'" in p for p in probs)
    assert any("v1: guest role 'producer'" in p for p in probs)
    assert any("unknown video_id 'v7'" in p for p in probs)
    assert "cast" not in wins[0]                     # v0 unjudged: nothing stamped
    assert wins[1]["cast"]["format"] == "solo"       # the earlier round's verdict still applies
    assert set(json.loads((tmp_path / "cast.json").read_text())) == {"v2", "v8"}


def test_aliases_drop_stop_words_homographs_and_the_host():
    assert cast_sheet.aliases_of(["Will Smith", "Gavin"], exclude={"gavin"}) == {"will smith", "smith"}
    assert cast_sheet.aliases_of(["host", "the"], exclude=set()) == set()
    assert cast_sheet.aliases_of(["Dr. Ann Lee"], exclude=set()) == {"ann lee", "ann"}


def test_cast_host_names_need_two_videos_and_skip_the_unnamed_host():
    cast = {"a": {"hosts": ["Eric"]}, "b": {"hosts": ["eric", "Marta"]}, "c": {"hosts": ["host"]},
            "d": {"hosts": ["host", "Marta"]}, "e": {"hosts": ["Zed"]}}
    assert cast_sheet.cast_host_names(cast) == ["Eric", "Marta"]
    # the sheets' own spelling, never title case
    assert cast_sheet.cast_host_names({"a": {"hosts": ["AJ"]}, "b": {"hosts": ["AJ"]}}) == ["AJ"]


# --------------------------------------------------------------------------- #
# caching the host's name on the channel record
# --------------------------------------------------------------------------- #
def _cast(*hosts_per_video):
    return {f"v{i}": {"hosts": list(h)} for i, h in enumerate(hosts_per_video)}


def test_host_name_certainty_needs_a_second_source_or_a_clear_majority():
    c = cast_sheet.host_name_certainty
    # the sheets and the names the fetch used agree: certain, fullest spelling stored
    r = c(_cast(["Joe"], ["Joe"], ["host"]), ["Joe", "Joe Rogan", "Rogan"], {})
    assert (r["confidence"], r["name"], r["videos"]) == ("high", "Joe Rogan", 2)
    assert r["sources"] == ["cast:2", "given"]
    # the sheets alone, in a few videos: not certain
    r = c(_cast(["AJ"], ["AJ"], ["AJ"], ["host"], ["host"]), [], {})
    assert (r["confidence"], r["name"]) == ("low", "AJ") and r["sources"] == ["cast:3"]
    # the sheets alone, in most of the videos that name a host: certain
    r = c(_cast(*([["AJ"]] * 5 + [["host"]] * 3 + [["Max"]] * 2)), [], {})
    assert (r["confidence"], r["name"]) == ("high", "AJ")
    # a name said outright on camera is the second source
    full = {"name_candidates": [{"name": "eric", "videos": 1, "said_outright": True}]}
    r = c(_cast(["Eric"], ["Eric"]), [], full)
    assert r["confidence"] == "high" and r["sources"] == ["cast:2", "on_camera"]
    # so is a name the descriptions give the host
    full = {"description_anchors": {"names": [{"name": "Eric Decker", "videos": 3}]}}
    assert c(_cast(["Eric"], ["Eric"]), [], full)["sources"] == ["cast:2", "descriptions"]
    assert c({}, ["Eric"], {})["confidence"] == "none"


def test_cache_host_name_reports_set_refused_and_missing_tool(tmp_path, monkeypatch):
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "calls.txt"
    (fake / "tl-internal").write_text(
        f"#!/bin/sh\necho \"$@\" >> {log}\nif [ \"$3\" = set ] && [ \"$4\" = 42 ]; then exit 0; fi\n"
        "echo 'Access denied: setting channel ai_description keys is restricted to superusers.' >&2\nexit 1\n")
    (fake / "tl-internal").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake))
    assert cast_sheet.cache_host_name(42, "Joe Rogan") == "set"
    assert log.read_text().splitlines() == ["channels ai-description set 42 host_name Joe Rogan"]
    assert cast_sheet.cache_host_name(7, "Joe Rogan").startswith("skipped: Access denied")
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert cast_sheet.cache_host_name(42, "Joe Rogan") == "skipped: tl-internal not available"


def _apply_with_context(tmp_path, monkeypatch, context: dict, host_names: str, cast_returns: dict):
    _render(tmp_path, monkeypatch, per_agent=2)
    rdir = tmp_path / "returns"
    for sheet, data in cast_returns.items():
        (rdir / f"cast-{sheet}.json").write_text(json.dumps(data))
    (tmp_path / "batches").mkdir(exist_ok=True)
    (tmp_path / "batches" / "batch-000.json").write_text(json.dumps([_window("v0", "x")]))
    ctx = tmp_path / "ctx.json"
    ctx.write_text(json.dumps(context))
    calls = []
    monkeypatch.setattr(cast_sheet, "cache_host_name",
                        lambda cid, name: calls.append((cid, name)) or "set")
    monkeypatch.setattr(sys, "argv", [
        "cast_sheet.py", "apply", "--sheets", str(tmp_path / "cast-sheets.json"),
        "--returns", str(rdir), "--batches", str(tmp_path / "batches"), "--out", str(tmp_path / "cast.json"),
        "--host-names", host_names, "--context-full", str(ctx)])
    lines = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: lines.append((a, k)))
    rc = cast_sheet.main()
    monkeypatch.undo()
    summary = json.loads([a[0] for a, k in lines if not k.get("file")][0])
    _apply_with_context.context_after = json.loads(ctx.read_text())
    return rc, summary["host_name_cache"], calls


def test_apply_caches_a_certain_host_name_once(tmp_path, monkeypatch):
    sheets = {"000": _SHEET0, "001": _SHEET1}        # Eric hosts v0 and v1
    rc, cache, calls = _apply_with_context(tmp_path, monkeypatch, {"channel_id": 42}, "Eric,Eric Decker", sheets)
    assert rc == 0 and cache["confidence"] == "high" and cache["cached"] == "set"
    assert calls == [(42, "Eric Decker")]
    # the context now says the host is settled, for the ledger write that follows
    assert _apply_with_context.context_after["cached_host_name"] == "Eric Decker"
    # already cached on the record: nothing is written, whatever the sheets say
    rc, cache, calls = _apply_with_context(tmp_path, monkeypatch, {"channel_id": 42, "cached_host_name": "Eric Decker"},
                                           "Eric,Eric Decker", sheets)
    assert cache["cached"] == "already set: Eric Decker" and calls == []
    # not certain: nothing is written
    rc, cache, calls = _apply_with_context(tmp_path, monkeypatch, {"channel_id": 42}, "", sheets)
    assert cache["confidence"] == "low" and cache["cached"] == "skipped: not certain" and calls == []
    # no channel id in the context: nothing is written
    rc, cache, calls = _apply_with_context(tmp_path, monkeypatch, {}, "Eric,Eric Decker", sheets)
    assert cache["cached"] == "skipped: no channel id in context" and calls == []


def test_host_name_certainty_never_lets_a_first_name_vouch_for_a_different_full_name():
    c = cast_sheet.host_name_certainty
    # the sheets say Joe Biden, the run was given Joe Rogan: no agreement, nothing certain
    r = c(_cast(["Joe Biden"], ["Joe Biden"]), ["Joe", "Joe Rogan", "Rogan"], {})
    assert (r["confidence"], r["name"], r["sources"]) == ("low", "Joe Biden", ["cast:2"])
    # a first name alone agrees with either full name
    r = c(_cast(["Joe"], ["Joe"]), ["Joe Rogan"], {})
    assert (r["confidence"], r["name"]) == ("high", "Joe Rogan")
    r = c(_cast(["Joe Biden"], ["Joe Biden"]), ["Joe"], {})
    assert (r["confidence"], r["name"]) == ("high", "Joe Biden")
    # the same discipline for the names said on camera and given by descriptions
    full = {"description_anchors": {"names": [{"name": "Joe Rogan", "videos": 3}]}}
    assert c(_cast(["Joe Biden"], ["Joe Biden"]), [], full)["sources"] == ["cast:2"]
    assert c(_cast(["Joe"], ["Joe"]), [], full)["sources"] == ["cast:2", "descriptions"]
    assert cast_sheet.names_agree("Joe Biden", "Joe Rogan") is False
    assert cast_sheet.names_agree("Joe", "Joe Rogan") and cast_sheet.names_agree("joe rogan", "Joe Rogan")
    assert cast_sheet.names_agree("", "Joe") is False


def test_a_two_word_channel_title_completes_a_first_name_host_only_when_the_surname_is_corroborated():
    c = cast_sheet.host_name_certainty
    cast = _cast(["Joe"], ["Joe"], ["Joe"])
    # the host says the surname outright on camera ("people call me Scott")
    said = {"name": "Joe Scott", "name_candidates": [{"name": "scott", "videos": 2, "said_outright": True,
                                                       "said_outright_videos": 2}]}
    r = c(cast, ["Joe"], said)
    assert (r["confidence"], r["name"]) == ("high", "Joe Scott") and "channel_title" in r["sources"]
    # the About text names the full title as a person
    about = {"name": "Sabine Hossenfelder", "about_text": "Sabine Hossenfelder has a PhD in physics."}
    assert c(_cast(["Sabine"], ["Sabine"]), ["Sabine"], about)["name"] == "Sabine Hossenfelder"
    # the upload descriptions give the full title
    anchors = {"name": "Eric Decker", "description_anchors": {"names": [{"name": "Eric Decker", "videos": 3}]}}
    assert c(_cast(["Eric"], ["Eric"]), ["Eric"], anchors)["name"] == "Eric Decker"
    # no corroboration: the first name stays, so a brand-like title is never taken for a person
    assert c(_cast(["Nick"], ["Nick"]), ["Nick"], {"name": "Nick Digital"})["name"] == "Nick"
    # the first word is not the host's name
    assert c(_cast(["Nick"], ["Nick"]), ["Nick"], {**about, "name": "Tech Nick"})["name"] == "Nick"
    # not exactly two words, or not words at all
    assert c(cast, ["Joe"], {**said, "name": "Answers With Joe"})["name"] == "Joe"
    assert c(cast, ["Joe"], {**said, "name": "Joe"})["name"] == "Joe"
    assert c(cast, ["Joe"], {**said, "name": "Joe 2000"})["name"] == "Joe"
    # a full name already known is never replaced, and an uncertain name is never extended
    assert c(_cast(["Joe Biden"], ["Joe Biden"]), ["Joe Biden"], said)["name"] == "Joe Biden"
    r = c(_cast(["Joe"], ["host"]), [], said)
    assert (r["confidence"], r["name"]) == ("low", "Joe")
    # an accented surname counts
    assert c(_cast(["José"], ["José"]), ["José"], {"name": "José García",
            "about_text": "José García es un youtuber."})["name"] == "José García"
