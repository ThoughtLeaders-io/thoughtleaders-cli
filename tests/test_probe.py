"""Tests for the tl-keyword-research probe.py script.

The script lives under skills/ (not the package), so we load it by path. ES is
mocked by patching the shared module's subprocess.run — probe.py runs every
query through kw_common.
"""
import importlib.util
import json
import subprocess
import time
from pathlib import Path

import pytest

_PROBE_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "probe.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_probe", _PROBE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load()
kw_common = probe.kw_common


@pytest.fixture(autouse=True)
def _isolated_probe_cache(monkeypatch, tmp_path):
    """Keep every probe test off the real on-disk response cache."""
    monkeypatch.setattr(probe, "CACHE_DIR", str(tmp_path / "probe-cache"))
    monkeypatch.setattr(kw_common, "_CACHE_NS", "test-identity")  # no `tl whoami` in tests


def _term_of(body):
    """Pull the searched term out of a built ES body (phrase, sqs or groups union)."""
    must = body["query"]["bool"]["must"][0]
    if "multi_match" in must:
        return must["multi_match"]["query"]
    if "bool" in must:  # the --groups-file union: every include group OR'd
        return " | ".join(f"({c['simple_query_string']['query']})"
                          for c in must["bool"]["should"])
    return must["simple_query_string"]["query"]


def _fields_of(body):
    """The fields the body's own clause searches ([] for the groups union)."""
    must = body["query"]["bool"]["must"][0]
    clause = must.get("multi_match") or must.get("simple_query_string") or {}
    return list(clause.get("fields") or [])


def _key_of(body):
    """Wave-1 bodies key on the term; wave-2 transcript-only bodies add a marker."""
    term = _term_of(body)
    if body["query"]["bool"].get("must_not") and _fields_of(body) == ["transcript"]:
        return (term, "transcript")
    return term


def _fake_run(spec):
    """subprocess.run stand-in answering by body.

    `spec` maps a term (or `(term, "transcript")` for the wave-2 body) to
    {"total", "distinct", "strata", "recent", "active", "rows"}.
    """
    calls = []

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        calls.append({"cmd": list(cmd), "body": body, "key": _key_of(body)})
        s = spec.get(_key_of(body), {})
        payload = {"results": list(s.get("rows") or [])[: body.get("size", 0)],
                   "total": s.get("total", 0)}
        aggs = {"distinct_channels": {"value": s.get("distinct", 0)}}
        if "strata" in s:
            aggs["strata"] = {"buckets": {k: {"doc_count": v} for k, v in s["strata"].items()}}
        if "recent" in s:
            docs, chans = s["recent"]
            aggs["recent_window"] = {"doc_count": docs, "recent_channels": {"value": chans}}
        if "active" in s:
            aggs["active_window"] = {"active_channels": {"value": s["active"]}}
        payload["aggregations"] = aggs
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    run.calls = calls
    return run


def _row(**kw):
    row = {"id": kw.get("id", 1), "title": kw.get("title", "a title"),
           "url": kw.get("url", "https://y/1"),
           "publication_date": kw.get("date", "2026-06-20T00:00:00"),
           "channel": {"id": kw.get("channel_id", 11), "content_category": "Marketing"}}
    if kw.get("highlight"):
        row["highlight"] = kw["highlight"]
    return row


def _run_main(monkeypatch, capsys, argv, run):
    monkeypatch.setattr(kw_common.subprocess, "run", run)
    monkeypatch.setattr(probe.sys, "argv", ["probe.py"] + argv)
    probe.main()
    return json.loads(capsys.readouterr().out)


class TestPureHelpers:
    def test_tokens(self):
        assert probe.tokens("TikTok Shop!") == ["tiktok", "shop"]

    def test_contiguous_sublist(self):
        assert probe.is_contiguous_sublist(["tiktok"], ["tiktok", "shop"])
        assert probe.is_contiguous_sublist(["tiktok", "shop"], ["tiktok", "shop", "affiliate"])
        assert not probe.is_contiguous_sublist(["shop", "tiktok"], ["tiktok", "shop"])
        assert not probe.is_contiguous_sublist(["tiktok", "shop"], ["tiktok", "shop"])  # equal != sub

    def test_base_field_strips_boost(self):
        assert probe.base_field("title^3") == "title"
        assert probe.base_field("ai.description") == "ai.description"

    def test_extract_distinct_reads_cardinality_agg(self):
        assert probe.extract_distinct({"aggregations": {"distinct_channels": {"value": 614}}}) == 614
        assert probe.extract_distinct({}) == 0

    def test_extract_recent_and_active(self):
        data = {"aggregations": {"recent_window": {"doc_count": 700,
                                                   "recent_channels": {"value": 120}}}}
        assert probe.extract_recent(data) == (700, 120)
        assert probe.extract_recent({}) == (0, 0)
        assert probe.extract_active({"aggregations": {"active_window": {"active_channels": {"value": 42}}}}) == 42
        assert probe.extract_active({}) == 0

    def test_extract_strata_defaults_missing_buckets_to_zero(self):
        data = {"aggregations": {"strata": {"buckets": {"title": {"doc_count": 5}}}}}
        assert probe.extract_strata(data, ["title", "summary_only"]) == {"title": 5, "summary_only": 0}

    def test_cut_is_word_boundary_and_within_limit(self):
        text = "word " * 100
        out = probe.cut(text, 20)
        assert len(out) <= 20 and out.endswith("…") and "  " not in out

    def test_to_snippet_converts_markers_and_cuts(self):
        raw = "<<match>> " + "filler " * 80
        out = probe.to_snippet(raw)
        assert out.startswith("«match»")
        assert "<<" not in out and ">>" not in out
        assert len(out) <= probe.SNIPPET_CHARS


class TestNormalize:
    def test_dedup_case_insensitive_first_wins(self):
        out = probe.normalize(["Crypto", "crypto", "bitcoin"], "phrase")
        assert [c["value"] for c in out] == ["Crypto", "bitcoin"]

    def test_dict_sqs_and_phrase(self):
        out = probe.normalize([{"sqs": "a +b", "label": "L"}, {"phrase": "c"}], "phrase")
        assert out[0] == {"label": "L", "value": "a +b", "mode": "sqs"}
        assert out[1]["mode"] == "phrase"


class TestNormalizeSqsAutoDetect:
    """A plain candidate carrying a simple_query_string operator is auto-promoted
    to sqs even when --mode wasn't passed (probed as a boolean group, not a literal
    phrase) — see probe.py normalize()/looks_like_sqs()."""

    @pytest.mark.parametrize("value", [
        "cannes +lions",                                          # +
        "advertising | agency",                                   # |
        "(advertising)",                                          # (  )
        "mythos5*",                                                # *
        "mythos5~1",                                               # ~
        "-keto",                                                   # leading - at start
        "cannes -keto",                                            # - after whitespace
        '-"film festival"',                                        # leading -"phrase"
        'cannes +lions +(advertising | agency) -"film festival"',  # combined, from the wild
    ])
    def test_operator_triggers_sqs(self, value):
        out = probe.normalize([value], "phrase")
        assert out[0]["mode"] == "sqs"

    def test_plain_phrase_stays_default_mode(self):
        out = probe.normalize(["cannes lions"], "phrase")
        assert out[0]["mode"] == "phrase"

    def test_quoted_phrase_alone_stays_default_mode(self):
        out = probe.normalize(['"cannes lions"'], "phrase")
        assert out[0]["mode"] == "phrase"

    def test_hyphenated_word_does_not_trigger(self):
        # a `-` inside a word is not an operator
        out = probe.normalize(["e-commerce"], "phrase")
        assert out[0]["mode"] == "phrase"

    def test_explicit_sqs_key_unaffected(self):
        out = probe.normalize([{"sqs": "plain text"}], "phrase")
        assert out[0]["mode"] == "sqs"

    def test_explicit_phrase_key_not_overridden(self):
        out = probe.normalize([{"phrase": "a +b"}], "phrase")
        assert out[0]["mode"] == "phrase"

    def test_value_dict_without_mode_auto_detects(self):
        out = probe.normalize([{"value": "a +b"}], "phrase")
        assert out[0]["mode"] == "sqs"

    def test_value_dict_with_explicit_mode_not_overridden(self):
        out = probe.normalize([{"value": "a +b", "mode": "phrase"}], "phrase")
        assert out[0]["mode"] == "phrase"

    def test_mode_sqs_flag_still_forces_everything(self):
        out = probe.normalize(["cannes lions"], "sqs")
        assert out[0]["mode"] == "sqs"


class TestBuildBody:
    def _body(self, **kw):
        cand = {"value": kw.pop("value", "tiktok shop"), "mode": kw.pop("mode", "phrase"),
                "label": "x"}
        kw.setdefault("fields", ["title", "summary", "transcript"])
        kw.setdefault("level", "topic")
        kw.setdefault("samples", 3)
        kw.setdefault("source_paths", probe.TOPIC_SOURCE)
        strata = kw.get("strata")
        level = kw.get("level")
        return probe.build_body(cand, **kw), probe.strata_names(level, kw["fields"]) if strata else []

    def test_phrase_scopes_doc_type_article(self):
        body, _ = self._body()
        flt = body["query"]["bool"]["filter"]
        assert {"term": {"doc_type": "article"}} in flt
        assert {"term": {"channel.format": 4}} in flt
        assert {"term": {"content_type": "longform"}} in flt
        assert body["track_total_hits"] is True and body["size"] == 3
        assert body["query"]["bool"]["must"][0]["multi_match"]["type"] == "phrase"

    def test_channel_level_doc_type_and_collapse(self):
        body, names = self._body(level="channel", fields=["name"],
                                 source_paths=probe.CHANNEL_SOURCE, strata=True)
        assert {"term": {"doc_type": "channel"}} in body["query"]["bool"]["filter"]
        assert body["collapse"] == {"field": "id"}
        assert names == [] and "strata" not in body["aggs"]     # channel level has no strata

    def test_strata_buckets_are_field_scoped(self):
        body, names = self._body(strata=True)
        assert names == ["title", "summary_only", "transcript_only"]
        buckets = body["aggs"]["strata"]["filters"]["filters"]
        assert buckets["title"]["bool"]["must"][0]["multi_match"]["fields"] == ["title"]
        assert "must_not" not in buckets["title"]["bool"]
        assert buckets["summary_only"]["bool"]["must"][0]["multi_match"]["fields"] == ["summary"]
        assert [c["multi_match"]["fields"] for c in buckets["summary_only"]["bool"]["must_not"]] == [["title"]]

    def test_strata_agg_never_touches_the_transcript(self):
        body, names = self._body(strata=True)
        # the slow field stays out of the agg: transcript_only is a subtraction
        assert set(body["aggs"]["strata"]["filters"]["filters"]) == {"title", "summary_only"}
        assert "transcript" not in json.dumps(body["aggs"]["strata"])
        assert probe.measured_strata_names(names) == ["title", "summary_only"]

    def test_highlight_query_is_the_candidates_own_clause(self):
        body, _ = self._body(highlight_fields=["title", "summary"])
        assert body["highlight"]["highlight_query"] == body["query"]["bool"]["must"][0]
        assert body["highlight"]["require_field_match"] is True

    def test_strata_omits_unprobed_fields(self):
        body, names = self._body(fields=["title", "summary"], strata=True)
        assert names == ["title", "summary_only"]
        assert set(body["aggs"]["strata"]["filters"]["filters"]) == {"title", "summary_only"}

    def test_strata_uses_sqs_form_for_sqs_candidates(self):
        body, _ = self._body(value='"mythos 5" -keto', mode="sqs", strata=True)
        bucket = body["aggs"]["strata"]["filters"]["filters"]["title"]["bool"]["must"][0]
        assert bucket["simple_query_string"] == {"query": '"mythos 5" -keto', "fields": ["title"],
                                                 "default_operator": "and"}

    def test_highlight_clause_over_probed_fields(self):
        body, _ = self._body(highlight_fields=["title", "summary"])
        hl = body["highlight"]
        assert set(hl["fields"]) == {"title", "summary"}
        assert hl["fields"]["title"]["fragment_size"] == probe.SNIPPET_CHARS
        assert hl["pre_tags"] == ["<<"]

    def test_source_is_identity_only(self):
        body, _ = self._body()
        assert "summary" not in body["_source"] and "transcript" not in body["_source"]
        assert "channel.id" in body["_source"] and "publication_date" in body["_source"]

    def test_recency_aggs_per_level(self):
        topic, _ = self._body(recency_cutoff="2025-06-18")
        assert topic["aggs"]["recent_window"]["filter"]["range"]["publication_date"] == {"gte": "2025-06-18"}
        channel, _ = self._body(level="channel", fields=["name"],
                                source_paths=probe.CHANNEL_SOURCE, recency_cutoff="active")
        assert channel["aggs"]["active_window"]["filter"]["range"]["posts_per_90_days"] == {"gt": 0}

    def test_date_range_filter(self):
        body, _ = self._body(since="2025-01-01", until="2026-01-01")
        ranges = [f for f in body["query"]["bool"]["filter"] if "range" in f]
        assert ranges[0]["range"]["publication_date"] == {"gte": "2025-01-01", "lte": "2026-01-01"}


class TestSubsumption:
    def test_marks_chain_not_drops(self):
        results = [
            {"keyword": "tiktok", "count": 100, "_mode": "phrase", "subsumed_by": []},
            {"keyword": "tiktok shop", "count": 50, "_mode": "phrase", "subsumed_by": []},
            {"keyword": "tiktok shop affiliate", "count": 5, "_mode": "phrase", "subsumed_by": []},
        ]
        probe.mark_subsumed(results, "OR")
        assert results[1]["subsumed_by"] == ["tiktok"]
        assert results[2]["subsumed_by"] == ["tiktok", "tiktok shop"]  # shortest first

    def test_no_subsumption_for_and(self):
        results = [
            {"keyword": "tiktok", "count": 100, "_mode": "phrase", "subsumed_by": []},
            {"keyword": "tiktok shop", "count": 50, "_mode": "phrase", "subsumed_by": []},
        ]
        probe.mark_subsumed(results, "AND")
        assert results[1]["subsumed_by"] == []


class TestArgValidation:
    def test_channel_level_ignores_scope_flags_with_one_note(self, monkeypatch, capsys):
        """A scope string is passed to every call of a run, so --level channel
        accepts --since/--until/--content-type and drops them on the floor."""
        run = _fake_run({"cooking": {"total": 10, "distinct": 4}})
        monkeypatch.setattr(kw_common.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--level", "channel", "--no-cache", "--no-recency",
                             "--samples", "0", "--since", "2025-01-01", "--until", "2026-01-01",
                             "--content-type", "short", "cooking"])
        probe.main()
        captured = capsys.readouterr()
        out = json.loads(captured.out)
        assert out["keywords"][0]["keyword"] == "cooking"
        assert out["scope"] == {"format": "youtube"}          # no content_type at channel level
        body = json.dumps(run.calls[0]["body"])
        assert "publication_date" not in body and "content_type" not in body
        assert captured.err.count(
            "--since/--until/--content-type ignored at --level channel") == 1

    def test_bad_date_format_rejected(self, monkeypatch):
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--since", "01-01-2025", "crypto"])
        with pytest.raises(SystemExit):
            probe.main()

    def test_bad_fields_rejected(self, monkeypatch):
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--fields", "title,bad field!", "crypto"])
        with pytest.raises(SystemExit):
            probe.main()


class TestMainEndToEnd:
    def test_keeps_all_nonzero_drops_empty(self, monkeypatch, capsys):
        run = _fake_run({"tiktok shop": {"total": 60000}, "rugpull-xyz": {"total": 0},
                         "tiktok": {"total": 40000000}})
        out = _run_main(monkeypatch, capsys,
                        ["--samples", "0", "--no-cache", "tiktok shop", "rugpull-xyz", "tiktok"], run)
        kw = {k["keyword"]: k for k in out["keywords"]}
        assert set(kw) == {"tiktok shop", "tiktok"}
        assert out["keywords"][0]["keyword"] == "tiktok"          # sorted desc by count
        assert kw["tiktok shop"]["subsumed_by"] == ["tiktok"]     # annotated, not dropped
        assert out["dropped"][0]["keyword"] == "rugpull-xyz"
        assert "empty" in out["dropped"][0]["signals"]

    def test_topic_and_channel_headline_counts(self, monkeypatch, capsys):
        run = _fake_run({"retirement planning": {"total": 34594, "distinct": 2447}})
        out = _run_main(monkeypatch, capsys,
                        ["--samples", "0", "--no-cache", "retirement planning"], run)
        k = out["keywords"][0]
        assert (k["documents"], k["channels"], k["count"]) == (34594, 2447, 34594)
        run2 = _fake_run({"retirement planning": {"total": 20876, "distinct": 614}})
        out2 = _run_main(monkeypatch, capsys,
                         ["--level", "channel", "--samples", "0", "--no-cache",
                          "retirement planning"], run2)
        k2 = out2["keywords"][0]
        assert (k2["documents"], k2["channels"], k2["count"]) == (20876, 614, 614)

    def test_topic_recency_classifies_fresh_thin_stale(self, monkeypatch, capsys):
        run = _fake_run({
            "retirement planning": {"total": 68000, "distinct": 8000, "recent": [14000, 2200]},
            "annuity": {"total": 110000, "distinct": 29000, "recent": [7000, 2300]},
            "myspace marketing": {"total": 40, "distinct": 19, "recent": [2, 2]},
            "disco fashion": {"total": 200, "distinct": 100, "recent": [1, 1]},
        })
        out = _run_main(monkeypatch, capsys,
                        ["--samples", "0", "--no-cache", "retirement planning", "annuity",
                         "myspace marketing", "disco fashion"], run)
        kw = {k["keyword"]: k for k in out["keywords"]}
        assert out["recency"]["months"] == 12 and "cutoff" in out["recency"]
        assert (kw["annuity"]["stale"], kw["annuity"]["thin"]) == (False, False)   # evergreen spared
        assert (kw["myspace marketing"]["stale"], kw["myspace marketing"]["thin"]) == (False, True)
        assert (kw["disco fashion"]["stale"], kw["disco fashion"]["thin"]) == (True, False)
        assert "thin" in kw["myspace marketing"]["signals"]
        assert "stale" in kw["disco fashion"]["signals"]

    def test_channel_recency_emits_active_channels(self, monkeypatch, capsys):
        run = _fake_run({"retirement planning": {"total": 20000, "distinct": 614, "active": 387}})
        out = _run_main(monkeypatch, capsys,
                        ["--level", "channel", "--samples", "0", "--no-cache",
                         "retirement planning"], run)
        k = out["keywords"][0]
        assert out["recency"]["signal"] == "posts_per_90_days>0"
        assert k["active_channels"] == 387 and k["stale"] is False

    def test_output_echoes_scope_and_opt_in_shape(self, monkeypatch, capsys):
        run = _fake_run({"retirement planning": {"total": 5000}})
        out = _run_main(monkeypatch, capsys,
                        ["--samples", "0", "--no-cache", "--content-type", "all",
                         "retirement planning"], run)
        assert out["scope"] == {"format": "youtube", "content_type": "all"}
        assert set(out) >= {"operator", "level", "fields", "scope", "keywords", "dropped",
                            "failed", "unresolved", "timing", "recency"}
        assert out["timing"]["waves"] == 1 and out["timing"]["unresolved"] == 0

    def test_no_recency_omits_recency_fields(self, monkeypatch, capsys):
        run = _fake_run({"retirement planning": {"total": 68000, "distinct": 8000}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-recency", "--samples", "0", "--no-cache", "retirement planning"], run)
        assert "recency" not in out and "stale" not in out["keywords"][0]

    def test_cache_serves_the_second_identical_run(self, monkeypatch, capsys):
        run = _fake_run({"alpha": {"total": 50}})
        _run_main(monkeypatch, capsys, ["--samples", "0", "alpha"], run)
        out = _run_main(monkeypatch, capsys, ["--samples", "0", "alpha"], run)
        assert len(run.calls) == 1
        assert out["timing"]["cache_hits"] == 1 and out["timing"]["es_calls"] == 0


class TestStrataAndSamples:
    SPEC = {
        "cannes lions": {
            "total": 1000, "distinct": 400,
            "strata": {"title": 200, "summary_only": 660, "transcript_only": 140},
            "rows": [
                _row(id=1, channel_id=12345, title="Cannes Lions 2026 winners",
                     highlight={"title": ["<<Cannes Lions>> 2026 winners"],
                                "summary": ["a recap of the <<Cannes Lions>> festival"]}),
                _row(id=2, channel_id=2345, title="Agency life",
                     highlight={"summary": ["…a recap of the <<Cannes Lions>> festival where agencies…"]}),
                _row(id=3, channel_id=999, title="No fragments here"),
            ],
        },
    }

    def test_asks_es_for_highlighting(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        assert "--highlight" in run.calls[0]["cmd"]

    def test_no_highlight_flag_skips_it(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--no-highlight", "cannes lions"], run)
        assert "--highlight" not in run.calls[0]["cmd"]
        assert "highlight" not in run.calls[0]["body"]

    def test_strata_counts_and_transcript_share(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        k = out["keywords"][0]
        assert k["strata"] == {"title": 200, "summary_only": 660, "transcript_only": 140}
        assert k["transcript_share"] == 0.14

    def test_transcript_share_zero_when_no_documents(self, monkeypatch, capsys):
        run = _fake_run({"nothing": {"total": 0, "strata": {"transcript_only": 0}}})
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "nothing"], run)
        assert out["keywords"] == [] and out["dropped"][0]["signals"] == ["empty"]

    def test_sample_field_stratum_and_snippet(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        s = out["keywords"][0]["samples"]
        # title + summary highlighted: the STRATUM is title, the SNIPPET comes from summary
        assert s[0]["stratum"] == "title" and s[0]["field"] == "summary"
        assert s[0]["snippet"] == "a recap of the «Cannes Lions» festival"
        assert s[0]["video_id"] == 1 and s[0]["channel_id"] == 12345
        assert s[0]["date"] == "2026-06-20" and s[0]["category"] == "Marketing"
        assert s[1]["stratum"] == "summary" and s[1]["field"] == "summary"
        # no fragments at all -> local window over the title
        assert s[2]["stratum"] == "title" and s[2]["field"] == "title"
        assert s[2]["snippet"] == "No fragments here"

    def test_long_snippet_is_cut_on_a_word_boundary(self, monkeypatch, capsys):
        long_frag = "<<cannes>> " + "advertising festival ".join(["word "] * 60)
        run = _fake_run({"cannes lions": {"total": 5, "rows": [
            _row(highlight={"transcript": [long_frag]})]}})
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        snippet = out["keywords"][0]["samples"][0]["snippet"]
        assert len(snippet) <= probe.SNIPPET_CHARS and snippet.endswith("…")
        assert snippet.startswith("«cannes»")

    def test_channel_level_samples_carry_name_and_topic(self, monkeypatch, capsys):
        rows = [{"id": 7, "name": "Chef Bob", "ai": {"topic_descriptions": "cooking videos"},
                 "highlight": {"name": ["<<Chef>> Bob"]}}]
        run = _fake_run({"cooking": {"total": 9, "distinct": 4, "rows": rows}})
        out = _run_main(monkeypatch, capsys,
                        ["--level", "channel", "--no-cache", "--no-recency", "cooking"], run)
        s = out["keywords"][0]["samples"][0]
        assert s == {"channel_id": 7, "name": "Chef Bob", "topic": "cooking videos",
                     "field": "name", "snippet": "«Chef» Bob"}
        assert "strata" not in out["keywords"][0]


class TestTranscriptWave:
    def _spec(self, transcript_only):
        return {
            "cannes lions": {
                "total": 1000, "distinct": 400,
                "strata": {"title": 100, "summary_only": 900 - transcript_only,
                           "transcript_only": transcript_only},
                "rows": [_row(id=1, highlight={"title": ["<<Cannes Lions>> recap"]})],
            },
            ("cannes lions", "transcript"): {
                "total": transcript_only, "distinct": 3,
                "rows": [_row(id=42, channel_id=77,
                              highlight={"transcript": ["we went to <<cannes lions>> last year"]})],
            },
        }

    def test_second_wave_fires_above_the_share_threshold(self, monkeypatch, capsys):
        run = _fake_run(self._spec(300))          # 30% >= 20% default
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        assert out["timing"]["waves"] == 2
        wave2 = [c for c in run.calls if c["key"] == ("cannes lions", "transcript")]
        assert len(wave2) == 1
        body = wave2[0]["body"]
        assert body["size"] == 2                                  # --transcript-samples default
        assert list(body["highlight"]["fields"]) == ["transcript"]
        assert [c["multi_match"]["fields"] for c in body["query"]["bool"]["must_not"]] == \
            [["title"], ["summary"]]
        extra = out["keywords"][0]["samples"][-1]
        assert extra["stratum"] == "transcript" and extra["channel_id"] == 77
        assert extra["snippet"] == "we went to «cannes lions» last year"

    def test_second_wave_skipped_below_the_threshold(self, monkeypatch, capsys):
        run = _fake_run(self._spec(100))          # 10% < 20% default
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "cannes lions"], run)
        assert out["timing"]["waves"] == 1
        assert not [c for c in run.calls if c["key"] == ("cannes lions", "transcript")]

    def test_second_wave_never_runs_at_channel_level(self, monkeypatch, capsys):
        run = _fake_run({"cooking": {"total": 100, "distinct": 40}})
        out = _run_main(monkeypatch, capsys,
                        ["--level", "channel", "--no-cache", "--no-recency", "cooking"], run)
        assert out["timing"]["waves"] == 1 and len(run.calls) == 1


class TestResidualAndExclusions:
    SPEC = {
        "cannes lions": {"total": 1000, "distinct": 400,
                         "strata": {"title": 200, "summary_only": 660, "transcript_only": 140},
                         "rows": [_row(id=1, highlight={"title": ["<<Cannes Lions>>"]})]},
        '"cannes lions" -(canneslions)': {
            "total": 346, "distinct": 61,
            "rows": [_row(id=9, channel_id=777,
                          highlight={"summary": ["<<young lions>> competition brief"]})]},
        '"cannes lions" -"film festival"': {"total": 959, "distinct": 380},
        "canneslions": {"total": 1000, "distinct": 400},
    }

    def test_residual_samples_marginal_share_and_breadth(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--residual-vs", "canneslions",
                         "cannes lions"], run)
        k = out["keywords"][0]
        assert k["residual"]["documents"] == 346 and k["residual"]["channels"] == 61
        assert k["residual"]["samples"][0]["channel_id"] == 777
        assert k["residual"]["samples"][0]["snippet"] == "«young lions» competition brief"
        assert k["marginal_share"] == 0.346
        assert k["breadth_vs_core"] == 1.0
        assert out["core"]["documents"] == 1000

    def test_exclusion_check_reports_removes_pct(self, monkeypatch, capsys):
        """Without --residual-vs there is no core to measure against: removes_pct
        (the cost to the CANDIDATE) is reported, but core_delta_pct is null and no
        over_cut/blocked signal is ever emitted from it."""
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--exclude-phrase", "film festival",
                         "cannes lions"], run)
        check = out["keywords"][0]["exclusion_checks"][0]
        assert check["phrase"] == "film festival"
        assert check["removes_pct"] == 4.1 and check["removes_pct_channels"] == 5.0
        assert check["delta_pct"] == 4.1  # deprecated alias of removes_pct, same value
        assert check["core_delta_pct"] is None and check["core_delta_pct_channels"] is None
        assert out["keywords"][0]["signals"] == []
        assert "exclusions" not in out


class TestCoreExclusionMeasurement:
    """`--residual-vs` + `--exclude-phrase` together measure what the exclusion
    costs the CORE, not just the candidate it's scoped inside — over_cut/blocked
    must come from that core measurement only (probe.py compute_signals())."""

    SPEC = {
        "cannes lions": {"total": 1000, "distinct": 400,
                         "strata": {"title": 500, "summary_only": 500, "transcript_only": 0},
                         "rows": [_row(id=1, highlight={"title": ["<<Cannes Lions>>"]})]},
        "cannes": {"total": 2000, "distinct": 800,
                  "strata": {"title": 1000, "summary_only": 1000, "transcript_only": 0}},
        "canneslions": {"total": 1000, "distinct": 400},
        '"cannes lions" -(canneslions)': {"total": 400, "distinct": 200},
        '"cannes" -(canneslions)': {"total": 800, "distinct": 400},
        '"cannes lions" -"film festival"': {"total": 700, "distinct": 280},
        '"cannes lions" -film': {"total": 850, "distinct": 340},
        '"cannes" -"film festival"': {"total": 1400, "distinct": 560},
        '"cannes" -film': {"total": 1700, "distinct": 680},
        '(canneslions) -"film festival"': {"total": 994, "distinct": 398},
        '(canneslions) -film': {"total": 760, "distinct": 304},
    }

    def test_removes_pct_and_core_delta_pct_are_distinct(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "canneslions",
                         "--exclude-phrase", "film festival", "--exclude-phrase", "film",
                         "cannes lions"], run)
        checks = {c["phrase"]: c for c in out["keywords"][0]["exclusion_checks"]}
        ff, film = checks["film festival"], checks["film"]
        assert ff["removes_pct"] == 30.0 and ff["removes_pct_channels"] == 30.0
        assert ff["core_delta_pct"] == 0.6 and ff["core_delta_pct_channels"] == 0.5
        assert film["removes_pct"] == 15.0
        assert film["core_delta_pct"] == 24.0

    def test_large_candidate_loss_no_signal_when_core_barely_moves(self, monkeypatch, capsys):
        # the candidate loses 30% of itself, but the core only loses 0.6% — no signal
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "canneslions", "--exclude-phrase", "film festival",
                         "cannes lions"], run)
        k = out["keywords"][0]
        assert k["exclusion_checks"][0]["removes_pct"] == 30.0
        assert k["exclusion_checks"][0]["core_delta_pct"] == 0.6
        assert k["signals"] == []

    def test_large_core_loss_is_flagged_on_the_exclusion_not_the_candidate(self, monkeypatch, capsys):
        """over_cut/blocked describe what the EXCLUSION costs the core, so they
        live in the top-level `exclusions` summary only — stamping them on every
        candidate carrying the exclusion said nothing about the candidate."""
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "canneslions", "--exclude-phrase", "film",
                         "cannes lions"], run)
        k = out["keywords"][0]
        assert k["exclusion_checks"][0]["core_delta_pct"] == 24.0
        assert k["signals"] == []
        assert out["exclusions"][0]["signals"] == ["over_cut", "blocked"]

    def test_top_level_exclusions_summary_one_per_phrase(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "canneslions",
                         "--exclude-phrase", "film festival", "--exclude-phrase", "film",
                         "cannes lions"], run)
        exclusions = {e["phrase"]: e for e in out["exclusions"]}
        assert exclusions["film festival"]["core_documents"] == 994
        assert exclusions["film festival"]["core_delta_pct"] == 0.6
        assert exclusions["film festival"]["signals"] == []
        assert exclusions["film"]["core_documents"] == 760
        assert exclusions["film"]["core_delta_pct"] == 24.0
        assert exclusions["film"]["signals"] == ["over_cut", "blocked"]

    def test_core_exclusion_probed_once_per_phrase_not_per_candidate(self, monkeypatch, capsys):
        run = _fake_run(self.SPEC)
        _run_main(monkeypatch, capsys,
                 ["--no-cache", "--no-recency", "--samples", "0",
                  "--residual-vs", "canneslions",
                  "--exclude-phrase", "film festival", "--exclude-phrase", "film",
                  "cannes lions", "cannes"], run)
        core_excl_calls = [c for c in run.calls if _term_of(c["body"]).startswith("(canneslions) -")]
        assert len(core_excl_calls) == 2  # one per phrase — 2 candidates x 2 phrases would be 4


class TestSignals:
    def _args(self):
        return probe.parse_args([])

    def test_empty_and_subsumed(self):
        a = self._args()
        assert probe.compute_signals({"documents": 0}, a) == ["empty"]
        assert probe.compute_signals({"documents": 5, "subsumed_by": ["x"]}, a) == ["subsumed"]

    def test_transcript_led_boundary(self):
        a = self._args()
        assert probe.compute_signals({"documents": 9, "transcript_share": 0.8}, a) == ["transcript_led"]
        assert probe.compute_signals({"documents": 9, "transcript_share": 0.79}, a) == []

    def test_stale_and_thin(self):
        a = self._args()
        assert probe.compute_signals({"documents": 9, "stale": True}, a) == ["stale"]
        assert probe.compute_signals({"documents": 9, "thin": True}, a) == ["thin"]

    def test_redundant_boundary(self):
        a = self._args()
        assert probe.compute_signals({"documents": 9, "marginal_share": 0.049}, a) == ["redundant"]
        assert probe.compute_signals({"documents": 9, "marginal_share": 0.05}, a) == []

    def test_too_broad_boundary(self):
        a = self._args()
        row = {"documents": 9, "marginal_share": 0.8, "breadth_vs_core": 10.0}
        assert probe.compute_signals(row, a) == ["too_broad"]
        assert probe.compute_signals({**row, "breadth_vs_core": 9.9}, a) == []
        assert probe.compute_signals({**row, "marginal_share": 0.79}, a) == []

    def test_over_cut_and_blocked_are_never_candidate_signals(self):
        # They are properties of an exclusion's effect on the CORE, so no
        # candidate carries them, however large the cut it measured.
        a = self._args()
        for delta in (2.1, 5.1, 90.0):
            row = {"documents": 9, "exclusion_checks": [{"core_delta_pct": delta}]}
            assert probe.compute_signals(row, a) == []

    def test_no_signal_from_candidate_level_removes_pct_either(self):
        a = self._args()
        # a huge candidate-level removes_pct with no core_delta_pct measured
        row = {"documents": 9, "exclusion_checks": [{"removes_pct": 90.0, "delta_pct": 90.0,
                                                      "core_delta_pct": None}]}
        assert probe.compute_signals(row, a) == []


class TestDeadlineAndFailures:
    def test_deadline_reports_unresolved_without_calling_es(self, monkeypatch, capsys):
        run = _fake_run({"alpha": {"total": 10}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--deadline-at", "0", "alpha"], run)
        assert run.calls == []
        assert out["unresolved"] == [{"keyword": "alpha", "reason": "deadline"}]
        assert out["failed"] == [] and out["keywords"] == []
        assert out["timing"]["unresolved"] == 1

    def test_deadline_from_env(self, monkeypatch, capsys):
        monkeypatch.setenv("TL_KW_DEADLINE_AT", "0")
        run = _fake_run({"alpha": {"total": 10}})
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", "alpha"], run)
        assert run.calls == [] and out["unresolved"][0]["reason"] == "deadline"

    def test_timeout_is_failed_and_never_retried(self, monkeypatch, capsys):
        '''The ES call itself is never retried; only the transcript-free
        fallback re-runs, and it is off here.'''
        calls = []

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            calls.append(cmd)
            raise subprocess.TimeoutExpired(cmd, timeout or 0)

        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--no-cache", "--no-recency", "--samples", "0",
                             "--no-transcript-fallback", "alpha"])
        monkeypatch.setattr(kw_common.subprocess, "run", run)
        with pytest.raises(SystemExit):
            probe.main()
        out = json.loads(capsys.readouterr().out)
        assert len(calls) == 1                       # a timeout is never retried
        assert out["failed"][0]["keyword"] == "alpha"
        assert out["failed"][0]["reason"] == "timeout"

    def test_one_failure_recorded_others_survive(self, monkeypatch, capsys):
        base = _fake_run({"crypto": {"total": 10}})

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            body = json.loads(input)
            if _term_of(body) == "bad":
                return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="server error")
            return base(cmd, input=input, capture_output=capture_output, text=text, timeout=timeout)

        out = _run_main(monkeypatch, capsys,
                        ["--samples", "0", "--no-cache", "--no-recency", "crypto", "bad"], run)
        assert [k["keyword"] for k in out["keywords"]] == ["crypto"]
        assert out["failed"][0]["reason"] == "error" and "server error" in out["failed"][0]["error"]


SHEET_OUT = {
    "operator": "OR", "level": "topic", "fields": ["title", "summary", "transcript"],
    "scope": {"format": "youtube", "content_type": "longform"},
    "keywords": [
        {"keyword": "cannes lions", "documents": 347, "channels": 143,
         "strata": {"title": 63, "summary_only": 235, "transcript_only": 49},
         "transcript_share": 0.1412, "signals": [],
         "samples": [
             {"field": "title", "channel_id": 12345, "date": "2026-06-20",
              "snippet": "«Cannes Lions» 2026 Grand Prix winners explained"},
             {"field": "summary", "channel_id": 2345, "date": "2026-05-02",
              "snippet": "…a recap of the «Cannes Lions» festival where agencies…"},
             {"field": "transcript", "channel_id": 999, "date": "2026-04-11",
              "snippet": "…when we went to «cannes lions» last year the…"},
         ],
         "residual": {"vs": "core", "documents": 120, "channels": 61,
                      "samples": [{"field": "summary", "channel_id": 777, "date": "2026-03-03",
                                   "snippet": "…«young lions» competition brief…"}]},
         "marginal_share": 0.346, "breadth_vs_core": 1.0,
         "exclusion_checks": [
             {"phrase": "film festival", "removes_pct": 30.0, "removes_pct_channels": 29.0,
              "delta_pct": 30.0, "core_delta_pct": 4.1, "core_delta_pct_channels": 4.0},
             {"phrase": "film", "removes_pct": 50.0, "removes_pct_channels": 48.0,
              "delta_pct": 50.0, "core_delta_pct": 24.0, "core_delta_pct_channels": 23.0}]},
        {"keyword": "cannes", "documents": 12004, "channels": 5120,
         "strata": {"title": 4100, "summary_only": 6000, "transcript_only": 1904},
         "transcript_share": 0.1586, "signals": ["too_broad"], "samples": []},
    ],
    "dropped": [],
    "failed": [{"keyword": "lions festival", "reason": "timeout"}],
    "unresolved": [{"keyword": "cannes young lions", "reason": "deadline"}],
    "timing": {"elapsed_seconds": 12.3},
}

SHEET_GOLDEN = """\
# Sample sheet · intent: channels covering the Cannes Lions advertising festival
scope: youtube longform · all dates · fields title,summary,transcript · 2 candidates · 12.3s · 1 failed · 1 unresolved
docs/ch = documents / distinct channels · strata = title / summary-only / transcript-only docs · «» marks the match

## 1. cannes lions — 347 docs / 143 ch · strata 63/235/49 · transcript 14% · flags: —
- [title] ch 12345 · 2026-06-20 · «Cannes Lions» 2026 Grand Prix winners explained
- [summary] ch 2345 · 2026-05-02 · …a recap of the «Cannes Lions» festival where agencies…
- [transcript] ch 999 · 2026-04-11 · …when we went to «cannes lions» last year the…
  residual vs core: 120 docs / 61 ch (35%) · breadth 1.0×
  - [summary] ch 777 · 2026-03-03 · …«young lions» competition brief…
  exclusions: -"film festival" → removes 30.0% of this candidate · core −4.1% · -film → removes 50.0% of this candidate · core −24.0%
## 2. cannes — 12,004 docs / 5,120 ch · strata 4,100/6,000/1,904 · transcript 16% · flags: too_broad
## failed / unresolved
- "lions festival" — timeout
- "cannes young lions" — deadline
"""


class TestSheet:
    def test_golden_sheet(self):
        sheet = probe.render_sheet(
            SHEET_OUT, intent="channels covering the Cannes Lions advertising festival",
            since=None, until=None, content_type="longform")
        assert sheet == SHEET_GOLDEN

    def test_core_summary_line_with_residual_vs(self):
        out = {**SHEET_OUT, "core": {"query": "canneslions", "documents": 1000, "channels": 400}}
        sheet = probe.render_sheet(out, intent="", since=None, until=None, content_type="longform")
        lines = sheet.splitlines()
        assert "core: canneslions — 1,000 docs / 400 ch" in lines
        # right after the header explainer line, before the blank line and the candidates
        idx = lines.index("core: canneslions — 1,000 docs / 400 ch")
        assert lines[idx - 1].startswith("docs/ch = documents")
        assert lines[idx + 1] == ""

    def test_no_core_summary_line_without_residual_vs(self):
        sheet = probe.render_sheet(SHEET_OUT, intent="", since=None, until=None,
                                   content_type="longform")
        assert not any(ln.startswith("core:") for ln in sheet.splitlines())

    def test_exclusion_line_shows_core_na_without_a_core(self):
        out = {**SHEET_OUT, "keywords": [{
            "keyword": "cannes lions", "documents": 1000, "channels": 400, "signals": [],
            "samples": [],
            "exclusion_checks": [{"phrase": "film festival", "removes_pct": 30.0,
                                  "removes_pct_channels": 30.0, "delta_pct": 30.0,
                                  "core_delta_pct": None, "core_delta_pct_channels": None}],
        }]}
        sheet = probe.render_sheet(out, intent="", since=None, until=None, content_type="longform")
        assert ('  exclusions: -"film festival" → removes 30.0% of this candidate · core n/a'
                in sheet.splitlines())

    def test_channel_level_rows(self):
        out = {"level": "channel", "fields": ["name"], "keywords": [
            {"keyword": "cooking", "documents": 20, "channels": 8, "signals": [],
             "samples": [{"channel_id": 7, "name": "Chef Bob", "topic": "x" * 200}]}],
            "dropped": [], "failed": [], "unresolved": [], "timing": {"elapsed_seconds": 1.0}}
        sheet = probe.render_sheet(out, intent="", since=None, until=None, content_type="longform")
        assert "# Sample sheet · intent: (none)" in sheet
        assert "scope: youtube channels · all dates" in sheet
        assert "## 1. cooking — 20 docs / 8 ch · flags: —" in sheet
        line = [ln for ln in sheet.splitlines() if ln.startswith("- ch 7")][0]
        assert line.startswith("- ch 7 · Chef Bob · ") and line.endswith("…")
        assert len(line.split(" · ")[2]) <= probe.SHEET_TOPIC_CHARS

    def test_main_writes_the_sheet_file(self, monkeypatch, capsys, tmp_path):
        run = _fake_run({"alpha": {"total": 10, "distinct": 4,
                                   "strata": {"title": 10, "summary_only": 0, "transcript_only": 0},
                                   "rows": [_row(highlight={"title": ["<<alpha>> post"]})]}})
        path = tmp_path / "sheet.md"
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--sheet", str(path), "--intent", "find alpha",
                   "alpha"], run)
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Sample sheet · intent: find alpha\n")
        assert "## 1. alpha — 10 docs / 4 ch · strata 10/0/0 · transcript 0% · flags: —" in text
        assert "- [title] ch 11 · 2026-06-20 · «alpha» post" in text


class TestTranscriptFallback:
    """A transcript-field query is the slow one; a timeout drops it and says so."""

    ANSWER = {"total": 100, "distinct": 40, "strata": {"title": 30, "summary_only": 25}}

    @staticmethod
    def _tl(answer):
        """A `tl` that times out on any body naming the transcript and answers
        the reduced body."""
        bodies = []

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            body = json.loads(input)
            bodies.append(body)
            if "transcript" in json.dumps(body):
                raise subprocess.TimeoutExpired(cmd, timeout or 0)
            aggs = {"distinct_channels": {"value": answer["distinct"]},
                    "strata": {"buckets": {k: {"doc_count": v}
                                           for k, v in answer["strata"].items()}}}
            payload = {"results": [], "total": answer["total"], "aggregations": aggs}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        run.bodies = bodies
        return run

    def test_one_reduced_retry_answers_and_is_recorded(self, monkeypatch, capsys):
        run = self._tl(self.ANSWER)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "alpha"], run)
        k = out["keywords"][0]
        assert k["fields_used"] == ["title", "summary"]
        assert "transcript_dropped" in k["signals"]
        assert k["note"] == probe.TRANSCRIPT_DROPPED_NOTE
        # the retry never looked at the transcript, so its stratum is unknown
        assert k["strata"]["transcript_only"] is None and k["transcript_share"] is None
        assert k["documents"] == 100 and k["channels"] == 40
        assert len(run.bodies) == 2                     # exactly one extra call
        assert "transcript" not in json.dumps(run.bodies[1])
        assert out["timing"]["es_calls"] == 2      # the timed-out call counts too

    def test_sheet_header_says_which_fields_answered(self, monkeypatch, capsys, tmp_path):
        run = self._tl(self.ANSWER)
        path = tmp_path / "sheet.md"
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--samples", "0", "--sheet", str(path),
                   "alpha"], run)
        head = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("## 1. ")][0]
        assert "· fields title,summary (transcript dropped: timeout)" in head
        assert "· transcript ?" in head

    def test_flag_disables_it_and_the_probe_fails(self, monkeypatch, capsys):
        run = self._tl(self.ANSWER)
        monkeypatch.setattr(kw_common.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--no-cache", "--no-recency", "--samples", "0",
                             "--no-transcript-fallback", "alpha"])
        with pytest.raises(SystemExit):
            probe.main()
        out = json.loads(capsys.readouterr().out)
        assert out["keywords"] == [] and len(run.bodies) == 1
        assert out["failed"][0] == {"keyword": "alpha", "label": "alpha", "reason": "timeout",
                                    "error": out["failed"][0]["error"]}

    def test_deadline_reached_before_the_retry_is_unresolved(self, monkeypatch, capsys):
        clock = {"t": 0.0}
        monkeypatch.setattr(kw_common.time, "monotonic", lambda: clock["t"])
        inner = self._tl(self.ANSWER)

        def run(cmd, input=None, **kwargs):
            clock["t"] += 60          # the timed-out call burned the whole budget
            return inner(cmd, input=input, **kwargs)

        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--deadline-at", str(int(time.time()) + 30), "alpha"], run)
        assert out["unresolved"] == [{"keyword": "alpha", "reason": "deadline"}]
        assert out["failed"] == [] and len(inner.bodies) == 1   # no second call


class TestStrataDerivation:
    def test_transcript_only_is_documents_minus_the_measured_strata(self, monkeypatch, capsys):
        run = _fake_run({"alpha": {"total": 100, "distinct": 40,
                                   "strata": {"title": 30, "summary_only": 25}}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "alpha"], run)
        k = out["keywords"][0]
        assert k["strata"] == {"title": 30, "summary_only": 25, "transcript_only": 45}
        assert k["transcript_share"] == 0.45
        assert "transcript" not in json.dumps(run.calls[0]["body"]["aggs"]["strata"])

    def test_negative_remainder_is_clamped_at_zero(self, monkeypatch, capsys):
        run = _fake_run({"alpha": {"total": 10, "distinct": 4,
                                   "strata": {"title": 8, "summary_only": 7}}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "alpha"], run)
        assert out["keywords"][0]["strata"]["transcript_only"] == 0

    def test_snippet_is_the_fragment_with_the_most_hits(self, monkeypatch, capsys):
        run = _fake_run({"cannes lions": {"total": 5, "distinct": 2, "rows": [
            _row(highlight={"summary": ["the <<advertising>> world"],
                            "transcript": ["at <<cannes>> <<lions>> the <<advertising>> jury"]})]}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "cannes lions"], run)
        sample = out["keywords"][0]["samples"][0]
        assert sample["field"] == "transcript"        # 3 hits beats the summary's 1
        assert sample["snippet"] == "at «cannes» «lions» the «advertising» jury"


GROUPS_FILE = {
    "default_content_fields": ["title", "summary"],
    "groups": [
        {"text": "cannes lions", "content_fields": ["title"]},
        {"text": "croisette"},
        {"text": "film festival", "exclude": True},
    ],
}
UNION_TERM = "(cannes lions) | (croisette)"


def _groups_file(tmp_path, spec=None):
    path = tmp_path / "groups.json"
    path.write_text(json.dumps(spec if spec is not None else GROUPS_FILE), encoding="utf-8")
    return str(path)


class TestGroupsFile:
    """`--groups-file` measures the filter as DELIVERED: each group on its own
    content_fields, the exclude groups subtracted, plus a `union` candidate for
    the whole thing (probe.py groups_file_candidates())."""

    SPEC = {"cannes lions": {"total": 300, "distinct": 100,
                             "strata": {"title": 300}},
            "croisette": {"total": 200, "distinct": 80,
                          "strata": {"title": 50, "summary_only": 150}},
            UNION_TERM: {"total": 450, "distinct": 150,
                         "strata": {"title": 350, "summary_only": 100}}}

    def _bodies(self, run):
        return {c["key"]: c["body"] for c in run.calls}

    def test_per_group_fields_reach_query_strata_and_highlight(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--groups-file", _groups_file(tmp_path)],
                        run)
        bodies = self._bodies(run)
        narrow = bodies["cannes lions"]
        assert _fields_of(narrow) == ["title"]
        assert list(narrow["aggs"]["strata"]["filters"]["filters"]) == ["title"]
        assert list(narrow["highlight"]["fields"]) == ["title"]
        wide = bodies["croisette"]
        assert _fields_of(wide) == ["title", "summary"]          # default_content_fields
        assert list(wide["aggs"]["strata"]["filters"]["filters"]) == ["title", "summary_only"]
        assert list(wide["highlight"]["fields"]) == ["title", "summary"]
        # the run default (title,summary,transcript) never reaches a group's query
        assert "transcript" not in json.dumps(narrow) + json.dumps(wide)
        rows = {k["keyword"]: k for k in out["keywords"]}
        assert rows["cannes lions"]["fields"] == ["title"]
        assert rows["croisette"]["fields"] == ["title", "summary"]

    def test_excluded_groups_become_must_not_on_every_candidate(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(self.SPEC)
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--samples", "0",
                   "--groups-file", _groups_file(tmp_path)], run)
        excluded = {"simple_query_string": {"query": "film festival",
                                            "fields": ["title", "summary"],
                                            "default_operator": "and"}}
        for body in self._bodies(run).values():
            assert body["query"]["bool"]["must_not"] == [excluded]

    def test_union_body_ors_the_groups_on_their_own_fields(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(self.SPEC)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--groups-file", _groups_file(tmp_path)], run)
        union = self._bodies(run)[UNION_TERM]
        assert union["query"]["bool"]["must"][0] == {"bool": {"minimum_should_match": 1, "should": [
            {"simple_query_string": {"query": "cannes lions", "fields": ["title"],
                                     "default_operator": "and"}},
            {"simple_query_string": {"query": "croisette", "fields": ["title", "summary"],
                                     "default_operator": "and"}}]}}
        # the strata agg measures the union field by field, dropping groups that
        # do not search that field
        title_bucket = union["aggs"]["strata"]["filters"]["filters"]["title"]["bool"]["must"][0]
        assert len(title_bucket["bool"]["should"]) == 2
        summary_bucket = union["aggs"]["strata"]["filters"]["filters"]["summary_only"]
        assert len(summary_bucket["bool"]["must"][0]["bool"]["should"]) == 1
        row = [k for k in out["keywords"] if k.get("union")][0]
        assert row["documents"] == 450 and row["keyword"] == UNION_TERM

    def test_sheet_shows_the_union_first_and_the_differing_fields(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(self.SPEC)
        path = tmp_path / "sheet.md"
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--samples", "0", "--sheet", str(path),
                   "--groups-file", _groups_file(tmp_path)], run)
        heads = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                 if ln.startswith("## ")]
        assert heads[0].startswith("## 0. union — 450 docs / 150 ch")
        assert "· fields title,summary" in heads[0]
        narrow = [h for h in heads if h.startswith("## 1. cannes lions")][0]
        assert "· fields title" in narrow and "· fields title,summary" not in narrow

    def test_combines_with_positional_candidates_and_residual_vs(self, monkeypatch, capsys, tmp_path):
        spec = {**self.SPEC, "cannes": {"total": 900, "distinct": 300,
                                        "strata": {"title": 400, "summary_only": 200}},
                '"cannes" -(canneslions)': {"total": 500, "distinct": 200},
                "canneslions": {"total": 100, "distinct": 50}}
        run = _fake_run(spec)
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--groups-file", _groups_file(tmp_path),
                         "--residual-vs", "canneslions", "cannes"], run)
        assert {k["keyword"] for k in out["keywords"]} >= {UNION_TERM, "cannes lions", "cannes"}
        # the positional candidate is measured raw (no group excludes on it)
        positional = [c["body"] for c in run.calls if _term_of(c["body"]) == "cannes"][0]
        assert "must_not" not in positional["query"]["bool"]
        # a group candidate cannot be re-expressed as `<text> -(core)`, so the
        # core is subtracted with another must_not on the same candidate
        residual = [c["body"] for c in run.calls
                    if _term_of(c["body"]) == "cannes lions"
                    and len(c["body"]["query"]["bool"].get("must_not") or []) == 2][0]
        # the core is ONE thing, so it is subtracted on the RUN fields even
        # though this group only searches `title` (probe.py main, kind="residual")
        assert residual["query"]["bool"]["must_not"][1] == {
            "simple_query_string": {"query": "canneslions",
                                    "fields": ["title", "summary", "transcript"],
                                    "default_operator": "and"}}


class TestRequiredTermFragmentRanking:
    """A fragment that marks only the alternative the clause fired on is not
    evidence; the one carrying the required anchor is (probe.py pick_fragment())."""

    QUERY = "croisette +(advertising|marketing|agency|brand)"

    def test_anchor_bearing_fragment_wins_a_hit_count_tie(self, monkeypatch, capsys):
        run = _fake_run({self.QUERY: {"total": 5, "distinct": 2, "rows": [_row(highlight={
            "summary": ["the <<marketing>> and <<advertising>> world"],
            "transcript": ["down on the <<croisette>> with an <<agency>>"]})]}})
        out = _run_main(monkeypatch, capsys, ["--no-cache", "--no-recency", self.QUERY], run)
        sample = out["keywords"][0]["samples"][0]
        assert sample["field"] == "transcript"   # 1 required term beats 0, same hit count
        assert "«croisette»" in sample["snippet"]

    def test_more_required_terms_beats_more_hits(self):
        frags = [{"field": "summary", "text": "<<advertising>> <<marketing>> <<brand>>", "hits": 3},
                 {"field": "transcript", "text": "the <<croisette>> at <<cannes>>", "hits": 2}]
        assert probe.pick_fragment(frags, ["croisette"])[1] == "transcript"
        assert probe.pick_fragment(frags, [])[1] == "summary"   # no anchor: hits decide

    def test_phrase_candidates_anchor_on_the_phrase_itself(self):
        assert probe.required_of({"mode": "phrase", "value": "cannes lions"}) == ["cannes lions"]
        assert probe.required_of({"mode": "sqs", "value": self.QUERY}) == ["croisette"]


class TestZeroDocCandidatesOnTheSheet:
    """A candidate that matched nothing must still be ON the sheet: when it
    silently vanished the model judged it anyway and --apply died on it."""

    def test_no_matches_section_lists_every_dropped_candidate(self):
        out = {**SHEET_OUT, "dropped": [
            {"keyword": "lions festival", "count": 0, "reason": "no_matches", "signals": ["empty"]},
            {"keyword": "croisette week", "count": 0, "reason": "no_matches", "signals": ["empty"]}]}
        lines = probe.render_sheet(out, intent="", since=None, until=None,
                                   content_type="longform").splitlines()
        assert "## no matches (0 docs)" in lines
        assert '- "lions festival" · 0 docs' in lines
        assert '- "croisette week" · 0 docs' in lines
        assert lines.index("## no matches (0 docs)") < lines.index("## failed / unresolved")

    def test_no_section_when_nothing_was_dropped(self):
        sheet = probe.render_sheet(SHEET_OUT, intent="", since=None, until=None,
                                   content_type="longform")
        assert "## no matches" not in sheet

    def test_main_lists_a_zero_document_candidate(self, monkeypatch, capsys, tmp_path):
        run = _fake_run({"alpha": {"total": 10, "distinct": 4}, "beta": {"total": 0}})
        path = tmp_path / "sheet.md"
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "--sheet", str(path),
                         "alpha", "beta"], run)
        assert [d["keyword"] for d in out["dropped"]] == ["beta"]
        assert '- "beta" · 0 docs' in path.read_text(encoding="utf-8").splitlines()


class TestExclusionSignalsOnTheCoreLine:
    """over_cut / blocked describe the exclusion, so the sheet reads them on the
    `core:` line — not as a flag on every candidate that carried the exclusion."""

    CORE_OUT = {
        **SHEET_OUT,
        "core": {"query": "canneslions", "documents": 1000, "channels": 400},
        "exclusions": [
            {"phrase": "film festival", "core_documents": 972, "core_delta_pct": 2.8,
             "core_delta_pct_channels": 2.5, "signals": ["over_cut"]},
            {"phrase": "trainer", "core_documents": 997, "core_delta_pct": 0.3,
             "core_delta_pct_channels": 0.2, "signals": []},
        ],
    }

    def test_core_line_carries_the_exclusions_and_their_signals(self):
        lines = probe.render_sheet(self.CORE_OUT, intent="", since=None, until=None,
                                   content_type="longform").splitlines()
        assert ('core: canneslions — 1,000 docs / 400 ch · exclusions on core: '
                '-"film festival" −2.8% (over_cut) · -trainer −0.3%') in lines

    def test_candidate_exclusion_line_has_no_signal_words(self):
        sheet = probe.render_sheet(self.CORE_OUT, intent="", since=None, until=None,
                                   content_type="longform")
        line = [ln for ln in sheet.splitlines() if ln.startswith("  exclusions:")][0]
        assert line == ('  exclusions: -"film festival" → removes 30.0% of this candidate · '
                        'core −4.1% · -film → removes 50.0% of this candidate · core −24.0%')
        assert "over_cut" not in line and "blocked" not in line

    def test_unmeasured_exclusion_reads_na(self):
        out = {**self.CORE_OUT, "exclusions": [{"phrase": "trainer", "core_delta_pct": None,
                                                "signals": []}]}
        line = [ln for ln in probe.render_sheet(out, intent="", since=None, until=None,
                                                content_type="longform").splitlines()
                if ln.startswith("core:")][0]
        assert line.endswith("exclusions on core: -trainer n/a")


class TestEsCallAccounting:
    """`timing.es_calls` is what the run SPENT, so a call that failed counts."""

    def test_a_failed_call_is_counted(self, monkeypatch, capsys):
        def run(cmd, input=None, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unknown field 'nope'")

        monkeypatch.setattr(kw_common.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--no-cache", "--no-recency", "--samples", "0", "alpha"])
        with pytest.raises(SystemExit):
            probe.main()
        out = json.loads(capsys.readouterr().out)
        assert out["failed"][0]["keyword"] == "alpha"
        assert out["timing"]["es_calls"] == 1

    def test_a_deadline_refusal_is_not_a_call(self, monkeypatch, capsys):
        run = _fake_run({"alpha": {"total": 10}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--deadline-at", "0", "alpha"], run)
        assert out["timing"]["es_calls"] == 0 and run.calls == []


# ------------------------------------------------------------ argv parsing

class TestIntermixedArgv:
    """Positionals may appear anywhere (probe.py parse_args →
    parse_intermixed_args); a mistyped flag is named, never searched for."""

    def test_keywords_after_options_are_parsed(self, monkeypatch, capsys):
        run = _fake_run({"cannes lions": {"total": 10, "distinct": 4},
                         "croisette": {"total": 5, "distinct": 2}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "cannes lions", "--no-recency", "--samples", "0",
                         "croisette"], run)
        assert {k["keyword"] for k in out["keywords"]} == {"cannes lions", "croisette"}

    def test_mistyped_option_is_rejected_by_name(self, monkeypatch, capsys):
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--sinse", "2025-01-01", "crypto"])
        with pytest.raises(SystemExit):
            probe.main()
        assert "--sinse" in capsys.readouterr().err

    def test_option_like_positional_is_rejected_by_name(self, monkeypatch, capsys):
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--", "--sinse"])
        with pytest.raises(SystemExit):
            probe.main()
        assert "--sinse" in capsys.readouterr().err


class TestGroupsFileIntent:
    """A groups-file round is not left reading `intent: (none)`."""

    def test_flag_intent_reaches_the_sheet(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(TestGroupsFile.SPEC)
        path = tmp_path / "sheet.md"
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--samples", "0",
                   "--groups-file", _groups_file(tmp_path), "--intent", "cannes coverage",
                   "--sheet", str(path)], run)
        assert path.read_text(encoding="utf-8").startswith(
            "# Sample sheet · intent: cannes coverage\n")

    def test_the_file_can_carry_the_intent(self, monkeypatch, capsys, tmp_path):
        run = _fake_run(TestGroupsFile.SPEC)
        path = tmp_path / "sheet.md"
        _run_main(monkeypatch, capsys,
                  ["--no-cache", "--no-recency", "--samples", "0",
                   "--groups-file", _groups_file(tmp_path, {**GROUPS_FILE,
                                                            "intent": "from the file"}),
                   "--sheet", str(path)], run)
        assert path.read_text(encoding="utf-8").startswith(
            "# Sample sheet · intent: from the file\n")


class TestCoreCandidate:
    """A candidate whose text IS the --residual-vs core adds nothing to itself,
    so `redundant` / `too_broad` would fire on every core and say nothing."""

    def test_core_candidate_is_marked_not_flagged(self, monkeypatch, capsys, tmp_path):
        run = _fake_run({"cannes lions": {"total": 300, "distinct": 100},
                         "Cannes   Lions": {"total": 300, "distinct": 100}})
        path = tmp_path / "sheet.md"
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "Cannes   Lions", "--sheet", str(path),
                         "cannes lions"], run)
        row = out["keywords"][0]
        assert row["is_core"] is True and row["marginal_share"] == 0.0
        assert "redundant" not in row["signals"] and "too_broad" not in row["signals"]
        head = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("## 1. ")][0]
        assert head.startswith("## 1. cannes lions (core) — 300 docs")

    def test_a_different_candidate_still_gets_redundant(self, monkeypatch, capsys):
        run = _fake_run({"cannes": {"total": 300, "distinct": 100},
                         "cannes lions": {"total": 300, "distinct": 100},
                         '"cannes" -(cannes lions)': {"total": 0, "distinct": 0}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--residual-vs", "cannes lions", "cannes"], run)
        row = out["keywords"][0]
        assert row["is_core"] is False and "redundant" in row["signals"]


class TestCandidateFieldsOnTheDropNote:
    def test_fields_used_are_the_candidates_own(self, monkeypatch, capsys, tmp_path):
        """A group that only ever searched title,transcript did not fall back to
        the RUN's title,summary (probe.py note_transcript_dropped)."""
        run = TestTranscriptFallback._tl(TestTranscriptFallback.ANSWER)
        spec = {"groups": [{"text": "alpha", "content_fields": ["title", "transcript"]}]}
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--groups-file", _groups_file(tmp_path, spec)], run)
        row = [k for k in out["keywords"] if k["keyword"] == "alpha"][0]
        assert row["fields_used"] == ["title"]


class TestTranscriptSampleFailure:
    """Wave 2 fetches transcript-only samples; when that call fails the row says
    so instead of quietly showing one-sided evidence."""

    @staticmethod
    def _tl():
        inner = _fake_run({"alpha": {"total": 100, "distinct": 40,
                                     "strata": {"title": 10, "summary_only": 10},
                                     "rows": [_row(highlight={"title": ["<<alpha>> post"]})]}})

        def run(cmd, input=None, **kwargs):
            if _key_of(json.loads(input)) == ("alpha", "transcript"):
                raise subprocess.TimeoutExpired(cmd, 1)
            return inner(cmd, input=input, **kwargs)
        return run

    def test_failure_is_recorded_on_the_row_and_the_sheet(self, monkeypatch, capsys, tmp_path):
        path = tmp_path / "sheet.md"
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--sheet", str(path), "alpha"],
                        self._tl())
        row = out["keywords"][0]
        assert row["measurement_errors"] == ["transcript_samples: timeout"]
        head = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("## 1. ")][0]
        assert "· transcript samples: failed" in head


class TestNonStandardStrata:
    """`--fields title,hashtags` has no transcript stratum, so the subtracted
    bucket is named after the fields that are actually left over."""

    def test_helpers_name_the_remainder(self):
        assert probe.strata_names("topic", ["title", "hashtags"]) == ["title", "hashtags_only"]
        assert probe.remainder_bucket_name(["title", "summary", "transcript"]) == "transcript_only"
        assert probe.remainder_bucket_name(["title", "summary"]) is None

    def test_row_and_sheet_use_the_computed_bucket_name(self, monkeypatch, capsys, tmp_path):
        run = _fake_run({"alpha": {"total": 100, "distinct": 40, "strata": {"title": 30}}})
        path = tmp_path / "sheet.md"
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0",
                         "--fields", "title,hashtags", "--sheet", str(path), "alpha"], run)
        k = out["keywords"][0]
        assert k["strata"] == {"title": 30, "hashtags_only": 70}
        assert k["transcript_share"] is None
        assert list(run.calls[0]["body"]["aggs"]["strata"]["filters"]["filters"]) == ["title"]
        head = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("## 1. ")][0]
        assert "· strata title 30/hashtags_only 70" in head
        assert "transcript" not in head


class TestCounterLock:
    def test_twenty_parallel_calls_count_twenty(self, monkeypatch, capsys):
        run = _fake_run({f"kw{i}": {"total": 10 + i, "distinct": 2} for i in range(20)})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "--workers", "20"]
                        + [f"kw{i}" for i in range(20)], run)
        assert len(out["keywords"]) == 20
        assert out["timing"]["es_calls"] == 20 and out["timing"]["cache_hits"] == 0


class TestDeduped:
    def test_case_only_duplicate_is_reported_with_what_survived(self, monkeypatch, capsys):
        run = _fake_run({"Crypto": {"total": 10, "distinct": 4}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "Crypto", "crypto"], run)
        assert [k["keyword"] for k in out["keywords"]] == ["Crypto"]
        assert out["deduped"] == [{"keyword": "crypto", "kept_as": "Crypto"}]

    def test_an_exact_repeat_is_not_reported(self, monkeypatch, capsys):
        run = _fake_run({"crypto": {"total": 10, "distinct": 4}})
        out = _run_main(monkeypatch, capsys,
                        ["--no-cache", "--no-recency", "--samples", "0", "crypto", "crypto"], run)
        assert out["deduped"] == []


class TestTopLevelOrAnchors:
    """`"cannes lions" | canneslions` — every required term is an ALTERNATIVE, so
    marking any one of them is full evidence (kw_common.required_is_alternation)."""

    EXPR = '"cannes lions" | (canneslions +2026)'

    def test_required_terms_are_the_union_of_the_alternatives(self):
        assert kw_common.required_terms('"cannes lions" | canneslions') == \
            ["cannes lions", "canneslions"]
        assert kw_common.required_is_alternation('"cannes lions" | canneslions') is True
        assert kw_common.required_is_alternation('cannes +lions') is False

    def test_any_alternative_scores_as_a_required_hit(self):
        required = kw_common.required_terms(self.EXPR)
        assert probe.marked_required("…the <<canneslions>> recap…", required, True) == 1

    def test_a_longer_alternative_does_not_outrank_a_shorter_one(self):
        required = kw_common.required_terms(self.EXPR)
        # same number of marked spans: only the REQUIRED-term count differs
        frags = [{"field": "summary", "text": "…<<cannes lions>> on the beach…", "hits": 1},
                 {"field": "transcript", "text": "…<<canneslions 2026>> recap…", "hits": 1}]
        assert probe.pick_fragment(frags, required, True)[1] == "summary"
        assert probe.pick_fragment(frags, required, False)[1] == "transcript"

    def test_required_any_of_reads_the_candidate(self):
        assert probe.required_any_of({"mode": "sqs", "value": self.EXPR}) is True
        assert probe.required_any_of({"mode": "phrase", "value": "cannes lions"}) is False
