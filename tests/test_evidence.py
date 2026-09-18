"""Tests for evidence.py — the one-call-per-100-channels evidence sheet.

`tl db es` is faked at `kw_common.subprocess.run` (the same seam the other
keyword-research tests use) and dispatches on the request body, so a test can
answer per channel chunk without touching the network.
"""
import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "tl-keyword-research" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kw_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ev():
    return _load("evidence")


@pytest.fixture
def calls():
    return []


def chunk_ids(body):
    """The channel ids a request body is pinned to."""
    for clause in body["query"]["bool"]["filter"]:
        if "terms" in clause and "channel.id" in clause["terms"]:
            return list(clause["terms"]["channel.id"])
    return []


def row(cid, vid, *, title="T", date="2026-06-20", url="u", highlight=None, name=None):
    doc = {"id": vid, "title": title, "publication_date": date, "url": url,
           "channel": {"id": cid, "name": name or f"ch{cid}"}}
    if highlight:
        doc["highlight"] = highlight
    return doc


def fake_tl(handler, calls):
    """A `subprocess.run` stand-in: `handler(body, chunk_ids)` → rows, or raises."""
    def run(cmd, input=None, **kwargs):
        calls.append({"cmd": list(cmd), "body": json.loads(input) if input else None})
        if "whoami" in cmd:
            return SimpleNamespace(returncode=0, stdout=json.dumps({"user": {"id": "u1"}}),
                                   stderr="")
        body = json.loads(input)
        result = handler(body, chunk_ids(body))
        if isinstance(result, BaseException):
            raise result
        return SimpleNamespace(returncode=0, stdout=json.dumps({"results": result}), stderr="")
    return run


def run_evidence(ev, monkeypatch, capsys, argv, handler, calls):
    monkeypatch.setattr(ev.kw.subprocess, "run", fake_tl(handler, calls))
    monkeypatch.setattr(ev.sys, "argv", ["evidence.py", *argv])
    ev.main()
    return json.loads(capsys.readouterr().out)


def intensity_file(tmp_path, channels):
    path = tmp_path / "intensity.json"
    path.write_text(json.dumps({"channels": channels}), encoding="utf-8")
    return str(path)


def es_bodies(calls):
    return [c for c in calls if "es" in c["cmd"]]


# ------------------------------------------------------------------- basics

class TestQuery:
    def test_argv_asks_for_highlighting(self, ev, monkeypatch, capsys, calls):
        run_evidence(ev, monkeypatch, capsys,
                     ["--group", '"cannes lions"', "--channels", "7", "--no-cache"],
                     lambda body, ids: [row(7, "v1")], calls)
        assert "--highlight" in calls[0]["cmd"]
        assert calls[0]["cmd"][:4] == ["tl", "db", "es", "-"]

    def test_body_collapses_and_scopes(self, ev, monkeypatch, capsys, calls):
        run_evidence(ev, monkeypatch, capsys,
                     ["--group", "investing", "--channels", "7,8", "--no-cache",
                      "--since", "2026-01-01", "--fragment-size", "120"],
                     lambda body, ids: [], calls)
        body = calls[0]["body"]
        assert body["collapse"] == {"field": "channel.id"}
        assert body["track_total_hits"] is False
        assert body["sort"] == [{"_score": "desc"}]
        assert body["size"] == 2
        assert chunk_ids(body) == [7, 8]
        assert {"range": {"publication_date": {"gte": "2026-01-01"}}} in body["query"]["bool"]["filter"]
        assert body["highlight"]["fields"]["summary"]["fragment_size"] == 120

    def test_chunks_at_100_and_keeps_request_order(self, ev, monkeypatch, capsys, calls):
        ids = list(range(1, 251))

        def handler(body, cids):
            return [row(c, f"v{c}") for c in reversed(cids)]

        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", ",".join(str(i) for i in ids),
                            "--max-channels", "250", "--no-cache", "--workers", "1"],
                           handler, calls)
        assert [len(chunk_ids(c["body"])) for c in es_bodies(calls)] == [100, 100, 50]
        assert [c["channel_id"] for c in out["channels"]] == ids
        assert out["requested"] == 250 and out["fetched"] == 250

    def test_groups_file_exclude_and_per_group_fields_reach_the_query(
            self, ev, monkeypatch, capsys, calls, tmp_path):
        path = tmp_path / "groups.json"
        path.write_text(json.dumps({
            "operator": "OR",
            "default_content_fields": ["title", "summary"],
            "groups": [{"text": "cannes lions"},
                       {"text": "young lions", "content_fields": ["title"]},
                       {"text": "film festival", "exclude": True}],
        }), encoding="utf-8")
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--groups-file", str(path), "--channels", "7", "--no-cache"],
                           lambda body, ids: [], calls)
        bool_q = calls[0]["body"]["query"]["bool"]
        expected = ev.kw.groups_query(ev.kw.load_groups_file(str(path)), operator="OR")
        assert bool_q["should"] == expected["should"]
        assert bool_q["must_not"] == expected["must_not"]
        assert bool_q["minimum_should_match"] == 1
        assert out["expression"]["expression"] == \
            "(cannes lions) OR (young lions) AND NOT (film festival)"

    def test_keywords_are_phrased_and_combined(self, ev, monkeypatch, capsys, calls):
        run_evidence(ev, monkeypatch, capsys,
                     ["cannes lions", "adweek", "--operator", "AND", "--channels", "7",
                      "--no-cache"],
                     lambda body, ids: [], calls)
        must = calls[0]["body"]["query"]["bool"]["must"]
        assert [c["simple_query_string"]["query"] for c in must] == ['"cannes lions"', "adweek"]


# ------------------------------------------------------------ selection

class TestSelection:
    def test_tier_filter_and_max_channels_in_file_order(self, ev, monkeypatch, capsys,
                                                        calls, tmp_path):
        path = intensity_file(tmp_path, [
            {"channel_id": 1, "tier": "core", "name": "A", "matching_uploads": 9},
            {"channel_id": 2, "tier": "one_off", "name": "B", "matching_uploads": 1},
            {"channel_id": 3, "tier": "recurring", "name": "C", "matching_uploads": 5},
            {"channel_id": 4, "tier": "core", "name": "D", "matching_uploads": 4},
        ])
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels-file", path,
                            "--tiers", "core,recurring", "--max-channels", "2", "--no-cache"],
                           lambda body, ids: [], calls)
        assert [c["channel_id"] for c in out["channels"]] == [1, 3]
        assert chunk_ids(calls[0]["body"]) == [1, 3]

    def test_channels_file_carries_counts_and_sponsorability(self, ev, monkeypatch, capsys,
                                                             calls, tmp_path):
        path = intensity_file(tmp_path, [
            {"channel_id": 5, "tier": "core", "name": "Named", "matching_uploads": 14,
             "recent_matching_uploads": 6, "topic_share": 0.62,
             "sponsorability": {"is_msn": True, "is_tpp": False}},
        ])
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels-file", path, "--no-cache"],
                           lambda body, ids: [row(5, "v5", name="From ES")], calls)
        ch = out["channels"][0]
        assert ch["name"] == "Named" and ch["tier"] == "core"
        assert ch["matching_uploads"] == 14 and ch["topic_share"] == 0.62
        assert ch["sponsorability"] == {"is_msn": True, "is_tpp": False}

    def test_channels_flag_takes_name_from_the_hit_and_leaves_tier_null(
            self, ev, monkeypatch, capsys, calls):
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5", "--no-cache"],
                           lambda body, ids: [row(5, "v5", name="From ES")], calls)
        ch = out["channels"][0]
        assert ch["name"] == "From ES" and ch["tier"] is None
        assert ch["matching_uploads"] is None and "sponsorability" not in ch


# -------------------------------------------------------------- snippets

class TestSnippets:
    def test_prefers_summary_then_transcript_and_converts_markers(
            self, ev, monkeypatch, capsys, calls):
        hl = {"title": ["<<cannes>> recap"], "transcript": ["we went to <<cannes>>"],
              "summary": ["…<<Cannes Lions>> Grand Prix…"]}
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5,6", "--chunk", "1",
                            "--workers", "1", "--no-cache"],
                           lambda body, ids: ([row(5, "v5", highlight=hl)] if ids == [5]
                                              else [row(6, "v6", highlight={
                                                  "title": ["<<cannes>> recap"],
                                                  "transcript": ["we went to <<cannes>>"]})]),
                           calls)
        first, second = out["channels"]
        assert first["evidence"][0]["field"] == "summary"
        assert first["evidence"][0]["snippet"] == "…«Cannes Lions» Grand Prix…"
        assert second["evidence"][0]["field"] == "transcript"
        assert second["evidence"][0]["snippet"] == "we went to «cannes»"

    def test_snippet_is_cut_on_a_word_boundary(self, ev, monkeypatch, capsys, calls):
        long = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5", "--fragment-size", "30",
                            "--no-cache"],
                           lambda body, ids: [row(5, "v5", highlight={"summary": [long]})],
                           calls)
        snippet = out["channels"][0]["evidence"][0]["snippet"]
        assert len(snippet) <= 30 and snippet.endswith("…") and " " in snippet
        assert long.startswith(snippet[:-1].rstrip())

    def test_title_fallback_when_no_highlight_comes_back(self, ev, monkeypatch, capsys, calls):
        title = "A long intro before the Cannes Lions award and a long tail after it"
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", '"cannes lions"', "--channels", "5", "--no-cache"],
                           lambda body, ids: [row(5, "v5", title=title)], calls)
        item = out["channels"][0]["evidence"][0]
        assert item["field"] == "title"
        assert "Cannes Lions" in item["snippet"]

    def test_title_is_capped_at_90_characters(self, ev, monkeypatch, capsys, calls):
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5", "--no-cache"],
                           lambda body, ids: [row(5, "v5", title="word " * 40)], calls)
        assert len(out["channels"][0]["evidence"][0]["title"]) <= 90


# ------------------------------------------------------- misses & failures

class TestOutcomes:
    def test_channel_without_a_hit_is_missing(self, ev, monkeypatch, capsys, calls):
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5,6", "--no-cache"],
                           lambda body, ids: [row(5, "v5")], calls)
        assert out["missing"] == [6]
        assert out["fetched"] == 1 and out["requested"] == 2
        assert out["channels"][1]["evidence"] == []

    def test_per_channel_two_excludes_pass_one_and_restricts_channels(
            self, ev, monkeypatch, capsys, calls):
        def handler(body, ids):
            if body["query"]["bool"].get("must_not"):
                return [row(5, "v5b", title="second")]
            return [row(5, "v5a", title="first")]

        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5,6", "--per-channel", "2",
                            "--no-cache", "--workers", "1"],
                           handler, calls)
        second = es_bodies(calls)[1]["body"]
        assert chunk_ids(second) == [5]  # only the channel that had a pass-1 hit
        assert {"terms": {"id": ["v5a"]}} in second["query"]["bool"]["must_not"]
        assert [e["video_id"] for e in out["channels"][0]["evidence"]] == ["v5a", "v5b"]

    def test_deadline_yields_unresolved_without_any_call(self, ev, monkeypatch, capsys, calls):
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5,6", "--no-cache",
                            "--deadline-at", "1"],
                           lambda body, ids: [], calls)
        assert calls == []
        assert out["unresolved"] == [5, 6]
        assert out["missing"] == [] and out["failed"] == []

    def test_timeout_fails_one_chunk_and_the_others_still_land(
            self, ev, monkeypatch, capsys, calls):
        def handler(body, ids):
            if ids == [6]:
                return subprocess.TimeoutExpired(["tl"], 20)
            return [row(ids[0], f"v{ids[0]}")]

        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "5,6,7", "--chunk", "1",
                            "--workers", "1", "--no-cache"],
                           handler, calls)
        assert [f["channel_ids"] for f in out["failed"]] == [[6]]
        assert out["failed"][0]["kind"] == "timeout" and out["failed"][0]["chunk_index"] == 1
        assert out["fetched"] == 2 and out["missing"] == []

    def test_cache_hit_skips_elasticsearch(self, ev, monkeypatch, capsys, calls, tmp_path):
        ev.kw._reset_cache_namespace()
        argv = ["--group", "x", "--channels", "5", "--cache-dir", str(tmp_path / "c")]
        first = run_evidence(ev, monkeypatch, capsys, argv,
                             lambda body, ids: [row(5, "v5")], calls)
        assert first["timing"]["es_calls"] == 1 and first["timing"]["cache_hits"] == 0
        before = len(es_bodies(calls))
        second = run_evidence(ev, monkeypatch, capsys, argv,
                              lambda body, ids: [row(5, "v5")], calls)
        ev.kw._reset_cache_namespace()
        assert len(es_bodies(calls)) == before
        assert second["timing"]["cache_hits"] == 1 and second["timing"]["es_calls"] == 0
        assert second["channels"][0]["evidence"][0]["video_id"] == "v5"


# ----------------------------------------------------------------- sheet

class TestSheet:
    def test_golden_sheet(self, ev, monkeypatch, capsys, calls, tmp_path):
        path = intensity_file(tmp_path, [
            {"channel_id": 10, "tier": "core", "name": "Some Channel", "matching_uploads": 14,
             "recent_matching_uploads": 6, "topic_share": 0.62},
            {"channel_id": 20, "tier": "recurring", "name": "Other Channel",
             "matching_uploads": 9, "recent_matching_uploads": 2, "topic_share": 0.51},
            {"channel_id": 40, "tier": "recurring", "name": "No Hit", "matching_uploads": 3,
             "recent_matching_uploads": 0, "topic_share": 0.2},
            {"channel_id": 30, "tier": "one_off", "name": "Timed Out", "matching_uploads": 1,
             "recent_matching_uploads": 0, "topic_share": 0.1},
        ])
        sheet = tmp_path / "evidence.md"

        def handler(body, ids):
            if ids == [10]:
                return [row(10, "v10", title="Cannes Lions 2026 recap", date="2026-06-20",
                            highlight={"summary": ["…<<Cannes Lions>> Grand Prix…"]})]
            if ids == [20]:
                return [row(20, "v20", title="Agency vlog", date="2026-04-11",
                            highlight={"transcript": ["…we went to <<cannes lions>>…"]})]
            if ids == [30]:
                return subprocess.TimeoutExpired(["tl"], 20)
            return []

        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", '"cannes lions"', "--channels-file", path,
                            "--chunk", "1", "--workers", "1", "--no-cache",
                            "--topic", "cannes", "--sheet", str(sheet)],
                           handler, calls)
        elapsed = out["timing"]["elapsed_seconds"]
        assert sheet.read_text(encoding="utf-8") == (
            f"# Evidence sheet · topic: cannes · 2/4 channels (core 1 · recurring 1) · "
            f"3 calls · {elapsed}s\n"
            "scope: youtube longform\n"
            "one line per channel: id · name · matching uploads (recent) · topic share · "
            "[field] snippet (date · title)\n"
            "\n"
            "## core\n"
            "- 10 · Some Channel · 14 up (6 rec) · 62% · [summary] …«Cannes Lions» Grand Prix… "
            "(2026-06-20 · Cannes Lions 2026 recap)\n"
            "\n"
            "## recurring\n"
            "- 20 · Other Channel · 9 up (2 rec) · 51% · [transcript] …we went to «cannes lions»… "
            "(2026-04-11 · Agency vlog)\n"
            "\n"
            "## missing (no upload matches the filter): 40\n"
            "\n"
            "## failed: chunk 3 (1 ids: 30) — timeout\n"   # m7: the ids, not just a count
        )

    def test_scope_line_shows_the_window_judged_under(self, ev, monkeypatch, capsys,
                                                      calls, tmp_path):
        sheet = tmp_path / "s.md"
        run_evidence(ev, monkeypatch, capsys,
                     ["--group", "x", "--channels", "5", "--since", "2025-09-19",
                      "--content-type", "all", "--workers", "1", "--no-cache",
                      "--sheet", str(sheet)],
                     lambda body, ids: [row(5, "v5", title="T", date="2026-01-01")], calls)
        assert sheet.read_text(encoding="utf-8").splitlines()[1] == \
            "scope: youtube all · 2025-09-19.."

    def test_second_evidence_item_is_a_continuation_line(self, ev, monkeypatch, capsys,
                                                         calls, tmp_path):
        sheet = tmp_path / "s.md"

        def handler(body, ids):
            if body["query"]["bool"].get("must_not"):
                return [row(5, "v5b", title="Later", date="2026-02-02")]
            return [row(5, "v5a", title="Earlier", date="2026-01-01")]

        run_evidence(ev, monkeypatch, capsys,
                     ["--group", "x", "--channels", "5", "--per-channel", "2",
                      "--workers", "1", "--no-cache", "--sheet", str(sheet)],
                     handler, calls)
        lines = sheet.read_text(encoding="utf-8").splitlines()
        assert lines[-1] == "  + [title] Later (2026-02-02 · Later)"
        assert lines[-2].startswith("- 5 · ch5 · [title] Earlier (2026-01-01 · Earlier)")


class TestHighlightScoping:
    def test_highlight_query_is_the_groups_without_the_scope(self, ev, monkeypatch, capsys,
                                                             calls):
        run_evidence(ev, monkeypatch, capsys,
                     ["--group", "cannes +lions", "--channels", "7", "--no-cache"],
                     lambda body, ids: [row(7, "v1")], calls)
        hl = calls[0]["body"]["highlight"]
        # a scope filter that highlights turns `channel.format: 4` into "PlayStation «4»"
        assert hl["require_field_match"] is True
        assert "filter" not in hl["highlight_query"]["bool"]
        assert hl["highlight_query"]["bool"]["should"][0]["simple_query_string"]["query"] \
            == "cannes +lions"

    def test_snippet_is_the_fragment_with_the_most_hits(self, ev, monkeypatch, capsys, calls):
        hl = {"summary": ["the <<advertising>> world"],
              "transcript": ["at <<cannes>> <<lions>> the <<advertising>> jury"]}
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "cannes +lions +advertising", "--channels", "5",
                            "--no-cache"],
                           lambda body, ids: [row(5, "v5", highlight=hl)], calls)
        item = out["channels"][0]["evidence"][0]
        assert item["field"] == "transcript"        # 3 hits beats the summary's 1
        assert item["snippet"] == "at «cannes» «lions» the «advertising» jury"


class TestEvidenceArgv:
    """Positionals may appear anywhere (evidence.py parse_intermixed_args)."""

    def test_keywords_after_options_are_parsed(self, ev, monkeypatch, capsys, calls):
        run_evidence(ev, monkeypatch, capsys,
                     ["--channels", "7", "cannes lions", "--no-cache", "adweek",
                      "--operator", "AND"],
                     lambda body, ids: [], calls)
        must = calls[0]["body"]["query"]["bool"]["must"]
        assert [c["simple_query_string"]["query"] for c in must] == ['"cannes lions"', "adweek"]

    def test_mistyped_option_is_rejected_by_name(self, ev, monkeypatch, capsys):
        monkeypatch.setattr(ev.sys, "argv", ["evidence.py", "--sinse", "2026-01-01", "cannes"])
        with pytest.raises(SystemExit):
            ev.main()
        assert "--sinse" in capsys.readouterr().err


class TestChunkWorkerErrors:
    """Anything a chunk worker raises is THAT chunk's failure, named with its
    channel ids — otherwise its channels fall through to `missing`, which reads
    as "the filter no longer reaches them"."""

    def test_a_non_es_error_names_the_chunks_channels(self, ev, monkeypatch, capsys, calls):
        real = ev.build_body

        def boom(spec, operator, chunk, args, fields, exclude_video_ids=None):
            if chunk == [20]:
                raise RuntimeError("kaboom")
            return real(spec, operator, chunk, args, fields,
                        exclude_video_ids=exclude_video_ids)

        monkeypatch.setattr(ev, "build_body", boom)
        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "10,20", "--chunk", "1",
                            "--workers", "1", "--no-cache"],
                           lambda body, ids: [row(ids[0], f"v{ids[0]}")], calls)
        assert out["failed"] == [{"chunk_index": 1, "channel_ids": [20], "kind": "error",
                                  "reason": "kaboom"}]
        assert out["missing"] == []          # 20 was never asked about, not unreachable


class TestSecondPass:
    """`--per-channel 2` is a bonus data point: losing it must not retract the
    evidence pass 1 already produced."""

    def test_pass_two_failure_lands_in_its_own_bucket(self, ev, monkeypatch, capsys, calls,
                                                      tmp_path):
        sheet = tmp_path / "evidence.md"
        seen = {"n": 0}

        def handler(body, ids):
            seen["n"] += 1
            if seen["n"] > 2:                      # both pass-2 calls time out
                return subprocess.TimeoutExpired(["tl"], 20)
            return [row(ids[0], f"v{ids[0]}")]

        out = run_evidence(ev, monkeypatch, capsys,
                           ["--group", "x", "--channels", "10,20", "--chunk", "1",
                            "--workers", "1", "--no-cache", "--per-channel", "2",
                            "--sheet", str(sheet)],
                           handler, calls)
        assert out["failed"] == [] and out["unresolved"] == []
        assert out["pass2_incomplete"] == [10, 20]
        assert out["fetched"] == 2 and out["missing"] == []
        assert "## second upload not fetched: 10, 20" in sheet.read_text(encoding="utf-8")
