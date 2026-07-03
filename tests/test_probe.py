"""Tests for the tl-keyword-research probe.py script.

The script lives under skills/ (not the package), so we load it by path. ES is
mocked by patching the module's subprocess.run.
"""
import importlib.util
import json
import subprocess
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


def _term_of(body):
    """Pull the searched term out of a built ES body (phrase or sqs)."""
    must = body["query"]["bool"]["must"][0]
    if "multi_match" in must:
        return must["multi_match"]["query"]
    return must["simple_query_string"]["query"]


def _fake_run(counts, samples=None, distinct=None, recent=None, active=None):
    """Return a subprocess.run stand-in that answers by the body's term.

    `distinct` (term -> distinct-channel count) populates the cardinality agg.
    `recent` (term -> [recent_documents, recent_channels]) populates the topic
    recency `recent_window` agg; `active` (term -> active_channels) the channel
    `active_window` agg. Aggs are emitted only for the maps provided.
    """
    samples = samples or {}

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        term = _term_of(body)
        rows = samples.get(term, [])
        payload = {"results": rows[: body.get("size", 0)], "total": counts.get(term, 0)}
        aggs = {}
        if distinct is not None:
            aggs["distinct_channels"] = {"value": distinct.get(term, 0)}
        if recent is not None:
            docs, chans = recent.get(term, [0, 0])
            aggs["recent_window"] = {"doc_count": docs, "recent_channels": {"value": chans}}
        if active is not None:
            aggs["active_window"] = {"active_channels": {"value": active.get(term, 0)}}
        if aggs:
            payload["aggregations"] = aggs
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    return run


class TestPureHelpers:
    def test_tokens(self):
        assert probe.tokens("TikTok Shop!") == ["tiktok", "shop"]

    def test_contiguous_sublist(self):
        assert probe.is_contiguous_sublist(["tiktok"], ["tiktok", "shop"])
        assert probe.is_contiguous_sublist(["tiktok", "shop"], ["tiktok", "shop", "affiliate"])
        assert not probe.is_contiguous_sublist(["shop", "tiktok"], ["tiktok", "shop"])
        assert not probe.is_contiguous_sublist(["tiktok", "shop"], ["tiktok", "shop"])  # equal != sub

    def test_valid_date(self):
        assert probe.valid_date("2025-01-01")
        assert not probe.valid_date("2025-13-99")
        assert not probe.valid_date("nope")

    def test_extract_total_envelope(self):
        assert probe.extract_total({"total": 42}) == 42

    def test_extract_total_hits_shape(self):
        assert probe.extract_total({"hits": {"total": {"value": 7}}}) == 7
        assert probe.extract_total({"hits": {"total": 3}}) == 3
        assert probe.extract_total({}) == 0

    def test_extract_samples_friendly_keys_and_trim(self):
        data = {"results": [{"title": "T", "summary": "x" * 600, "channel": {"id": 5}}]}
        out = probe.extract_samples(data, probe.TOPIC_SAMPLE_FIELDS)
        assert out[0]["title"] == "T"
        assert out[0]["channel_id"] == 5          # friendly key, from channel.id
        assert len(out[0]["summary"]) == 500       # trimmed
        assert out[0]["url"] is None               # missing -> None

    def test_extract_samples_channel_keys(self):
        data = {"results": [{"name": "Foo", "ai": {"topic_descriptions": "cooking videos", "description": "d"}, "id": 9}]}
        out = probe.extract_samples(data, probe.CHANNEL_SAMPLE_FIELDS)
        assert out[0]["name"] == "Foo"
        assert out[0]["topic"] == "cooking videos"          # from ai.topic_descriptions
        assert out[0]["channel_description"] == "d"          # from ai.description
        assert out[0]["channel_id"] == 9

    def test_extract_distinct_reads_cardinality_agg(self):
        assert probe.extract_distinct({"aggregations": {"distinct_channels": {"value": 614}}}) == 614
        assert probe.extract_distinct({"aggs": {"distinct_channels": {"value": 7}}}) == 7
        assert probe.extract_distinct({}) == 0               # no agg -> 0
        assert probe.extract_distinct({"total": 99}) == 0    # only total present

    def test_extract_recent_reads_window_agg(self):
        data = {"aggregations": {"recent_window": {"doc_count": 700, "recent_channels": {"value": 120}}}}
        assert probe.extract_recent(data) == (700, 120)
        assert probe.extract_recent({}) == (0, 0)            # absent -> zeros

    def test_extract_active_reads_window_agg(self):
        data = {"aggregations": {"active_window": {"active_channels": {"value": 42}}}}
        assert probe.extract_active(data) == 42
        assert probe.extract_active({}) == 0                 # absent -> 0

    def test_months_ago_iso_is_earlier_and_iso(self):
        iso = probe.months_ago_iso(12)
        assert len(iso) == 10 and iso[4] == "-" and iso[7] == "-"   # YYYY-MM-DD
        assert iso < probe.datetime.date.today().isoformat()        # in the past


class TestNormalize:
    def test_dedup_case_insensitive_first_wins(self):
        out = probe.normalize(["Crypto", "crypto", "bitcoin"], "phrase")
        assert [c["value"] for c in out] == ["Crypto", "bitcoin"]

    def test_dict_sqs_and_phrase(self):
        out = probe.normalize([{"sqs": "a +b", "label": "L"}, {"phrase": "c"}], "phrase")
        assert out[0] == {"label": "L", "value": "a +b", "mode": "sqs"}
        assert out[1]["mode"] == "phrase"

    def test_label_falls_back_to_value(self):
        out = probe.normalize([{"value": "kw", "label": "   "}], "phrase")
        assert out[0]["label"] == "kw"


class TestBuildBody:
    def test_phrase_scopes_doc_type_article(self):
        body = probe.build_body(
            {"value": "tiktok shop", "mode": "phrase", "label": "x"},
            fields=["title", "summary"], level="topic", samples=5,
            source_paths=["title"], since=None, until=None,
        )
        flt = body["query"]["bool"]["filter"]
        assert {"term": {"doc_type": "article"}} in flt
        assert body["track_total_hits"] is True
        assert body["size"] == 5
        assert body["query"]["bool"]["must"][0]["multi_match"]["type"] == "phrase"

    def test_channel_level_doc_type(self):
        body = probe.build_body(
            {"value": "cooking", "mode": "phrase", "label": "x"},
            fields=["name"], level="channel", samples=0,
            source_paths=["name"], since=None, until=None,
        )
        assert {"term": {"doc_type": "channel"}} in body["query"]["bool"]["filter"]

    def test_collapse_and_cardinality_topic(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=5,
            source_paths=["title"], since=None, until=None,
        )
        # topic-level channel identity is nested under channel.id
        assert body["collapse"] == {"field": "channel.id"}
        assert body["aggs"]["distinct_channels"]["cardinality"]["field"] == "channel.id"

    def test_collapse_and_cardinality_channel(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["name"], level="channel", samples=5,
            source_paths=["name"], since=None, until=None,
        )
        # channel docs carry their own id
        assert body["collapse"] == {"field": "id"}
        assert body["aggs"]["distinct_channels"]["cardinality"]["field"] == "id"

    def test_topic_scopes_youtube_and_longform_by_default(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None,
        )
        flt = body["query"]["bool"]["filter"]
        assert {"term": {"channel.format": 4}} in flt            # YouTube only
        assert {"term": {"content_type": "longform"}} in flt     # longform default

    def test_topic_content_type_all_drops_longform_filter(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None, content_type="all",
        )
        flt = body["query"]["bool"]["filter"]
        assert {"term": {"channel.format": 4}} in flt            # format still enforced
        assert not any("content_type" in f.get("term", {}) for f in flt)  # no content_type filter

    def test_topic_content_type_short(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None, content_type="short",
        )
        assert {"term": {"content_type": "short"}} in body["query"]["bool"]["filter"]

    def test_channel_scopes_youtube_no_content_type(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["name"], level="channel", samples=0,
            source_paths=["name"], since=None, until=None,
        )
        flt = body["query"]["bool"]["filter"]
        assert {"term": {"format": 4}} in flt                    # channel-level format field
        assert not any("content_type" in f.get("term", {}) for f in flt)  # channels have none

    def test_recency_agg_topic_uses_publication_date_window(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None, recency_cutoff="2025-06-18",
        )
        rw = body["aggs"]["recent_window"]
        assert rw["filter"]["range"]["publication_date"] == {"gte": "2025-06-18"}
        assert rw["aggs"]["recent_channels"]["cardinality"]["field"] == "channel.id"
        assert "active_window" not in body["aggs"]            # topic uses date, not posts

    def test_recency_agg_channel_uses_posts_per_90_days(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["name"], level="channel", samples=0,
            source_paths=["name"], since=None, until=None, recency_cutoff="active",
        )
        aw = body["aggs"]["active_window"]
        assert aw["filter"]["range"]["posts_per_90_days"] == {"gt": 0}
        assert aw["aggs"]["active_channels"]["cardinality"]["field"] == "id"
        assert "recent_window" not in body["aggs"]            # channel has no date window

    def test_no_recency_cutoff_means_no_recency_agg(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None, recency_cutoff=None,
        )
        assert set(body["aggs"]) == {"distinct_channels"}    # only the all-time distinct agg

    def test_sqs_mode(self):
        body = probe.build_body(
            {"value": '"tiktok shop" +amazon', "mode": "sqs", "label": "x"},
            fields=["title^3", "summary"], level="topic", samples=0,
            source_paths=["title"], since=None, until=None,
        )
        sqs = body["query"]["bool"]["must"][0]["simple_query_string"]
        assert sqs["query"] == '"tiktok shop" +amazon'
        assert sqs["fields"] == ["title^3", "summary"]

    def test_date_range_filter(self):
        body = probe.build_body(
            {"value": "x", "mode": "phrase", "label": "x"},
            fields=["title"], level="topic", samples=0,
            source_paths=["title"], since="2025-01-01", until="2026-01-01",
        )
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
        assert results[0]["subsumed_by"] == []
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
    def test_channel_level_rejects_date(self, monkeypatch):
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--level", "channel", "--since", "2025-01-01", "cooking"])
        with pytest.raises(SystemExit):
            probe.main()

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
        counts = {"tiktok shop": 60000, "rugpull-xyz": 0, "tiktok": 40000000}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0", "tiktok shop", "rugpull-xyz", "tiktok"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        kw = {k["keyword"]: k for k in out["keywords"]}
        assert set(kw) == {"tiktok shop", "tiktok"}            # nonzero kept
        assert out["keywords"][0]["keyword"] == "tiktok"        # sorted desc by count
        assert kw["tiktok shop"]["subsumed_by"] == ["tiktok"]   # annotated, not dropped
        assert out["dropped"] == [{"keyword": "rugpull-xyz", "count": 0, "reason": "no_matches"}]

    def test_operator_and_no_subsumption(self, monkeypatch, capsys):
        counts = {"tiktok shop": 50, "tiktok shop affiliate": 5}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--operator", "AND", "--samples", "0",
                             "tiktok shop", "tiktok shop affiliate"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        assert all(k["subsumed_by"] == [] for k in out["keywords"])  # no annotation under AND

    def test_topic_level_count_is_documents_plus_channels(self, monkeypatch, capsys):
        counts = {"retirement planning": 34594}
        distinct = {"retirement planning": 2447}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts, distinct=distinct))
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--samples", "0", "retirement planning"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        k = out["keywords"][0]
        assert k["documents"] == 34594          # raw video total
        assert k["channels"] == 2447            # distinct channels (breadth signal)
        assert k["count"] == 34594              # topic headline == documents

    def test_channel_level_count_is_distinct_channels(self, monkeypatch, capsys):
        # raw doc total is inflated by per-quarter index duplication; the headline
        # count must be the distinct-channel cardinality, not the doc total.
        counts = {"retirement planning": 20876}
        distinct = {"retirement planning": 614}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts, distinct=distinct))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--level", "channel", "--samples", "0", "retirement planning"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        k = out["keywords"][0]
        assert k["documents"] == 20876          # raw (inflated) channel-doc total, kept for reference
        assert k["channels"] == 614             # distinct channels
        assert k["count"] == 614                # channel headline == distinct channels

    def test_topic_recency_classifies_fresh_thin_stale(self, monkeypatch, capsys):
        counts = {"retirement planning": 68000, "annuity": 110000, "myspace marketing": 40, "disco fashion": 200}
        distinct = {"retirement planning": 8000, "annuity": 29000, "myspace marketing": 19, "disco fashion": 100}
        # [recent_documents, recent_channels]
        recent = {
            "retirement planning": [14000, 2200],   # share 27% -> FRESH
            "annuity": [7000, 2300],                 # share 8% but 2300 >= 5 floor -> FRESH (evergreen)
            "myspace marketing": [2, 2],             # 2<5 but share 10.5% (>=10%) -> THIN, not stale
            "disco fashion": [1, 1],                 # 1<5 and share 1% (<10%) -> STALE
        }
        monkeypatch.setattr(probe.subprocess, "run",
                            _fake_run(counts, distinct=distinct, recent=recent))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0",
                             "retirement planning", "annuity", "myspace marketing", "disco fashion"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        kw = {k["keyword"]: k for k in out["keywords"]}
        assert out["recency"]["months"] == 12 and "cutoff" in out["recency"]
        assert kw["retirement planning"]["recent_channels"] == 2200
        assert (kw["retirement planning"]["stale"], kw["retirement planning"]["thin"]) == (False, False)
        assert (kw["annuity"]["stale"], kw["annuity"]["thin"]) == (False, False)        # evergreen spared
        assert (kw["myspace marketing"]["stale"], kw["myspace marketing"]["thin"]) == (False, True)
        assert (kw["disco fashion"]["stale"], kw["disco fashion"]["thin"]) == (True, False)
        assert "recent_channels" in kw["disco fashion"]["stale_reason"]

    def test_channel_recency_emits_active_channels(self, monkeypatch, capsys):
        counts = {"retirement planning": 20000}     # raw channel-doc total
        distinct = {"retirement planning": 614}     # all-time distinct channels
        active = {"retirement planning": 387}       # posts_per_90_days>0
        monkeypatch.setattr(probe.subprocess, "run",
                            _fake_run(counts, distinct=distinct, active=active))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--level", "channel", "--samples", "0", "retirement planning"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        k = out["keywords"][0]
        assert out["recency"]["signal"] == "posts_per_90_days>0"
        assert k["count"] == 614 and k["active_channels"] == 387
        assert k["active_channel_share"] == round(387 / 614, 4)
        assert k["stale"] is False                  # 63% active

    def test_output_echoes_scope(self, monkeypatch, capsys):
        counts = {"retirement planning": 5000}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0", "--content-type", "all", "retirement planning"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        assert out["scope"] == {"format": "youtube", "content_type": "all"}

    def test_no_recency_omits_recency_fields(self, monkeypatch, capsys):
        counts = {"retirement planning": 68000}
        distinct = {"retirement planning": 8000}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts, distinct=distinct))
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--no-recency", "--samples", "0", "retirement planning"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        assert "recency" not in out
        assert "recent_channels" not in out["keywords"][0]
        assert "stale" not in out["keywords"][0]

    def test_samples_friendly_keys(self, monkeypatch, capsys):
        counts = {"tiktok shop": 2}
        samples = {"tiktok shop": [{"title": "Selling on TikTok Shop", "summary": "guide", "channel": {"id": 1}, "url": "u"}]}
        monkeypatch.setattr(probe.subprocess, "run", _fake_run(counts, samples))
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--samples", "3", "tiktok shop"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        s = out["keywords"][0]["samples"][0]
        assert s["title"] == "Selling on TikTok Shop"
        assert s["channel_id"] == 1
        assert s["url"] == "u"


class TestFailureResilience:
    """One slow/broken candidate must not abort the batch (probe emits `failed`)."""

    def test_one_failure_recorded_others_survive(self, monkeypatch, capsys):
        base = _fake_run({"crypto": 10})

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            body = json.loads(input)
            if _term_of(body) == "heavy term":
                raise subprocess.TimeoutExpired(cmd, timeout or 0)
            return base(cmd, input=input, capture_output=capture_output, text=text, timeout=timeout)

        monkeypatch.setattr(probe.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0", "--no-recency", "crypto", "heavy term"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        assert [k["keyword"] for k in out["keywords"]] == ["crypto"]
        assert [f["keyword"] for f in out["failed"]] == ["heavy term"]
        assert "timed out" in out["failed"][0]["error"]

    def test_nonzero_exit_failure_recorded(self, monkeypatch, capsys):
        base = _fake_run({"crypto": 10})

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            body = json.loads(input)
            if _term_of(body) == "bad":
                return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="server error")
            return base(cmd, input=input, capture_output=capture_output, text=text, timeout=timeout)

        monkeypatch.setattr(probe.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0", "--no-recency", "crypto", "bad"])
        probe.main()
        out = json.loads(capsys.readouterr().out)
        assert [k["keyword"] for k in out["keywords"]] == ["crypto"]
        assert "server error" in out["failed"][0]["error"]

    def test_all_failures_exit_nonzero_but_json_still_emitted(self, monkeypatch, capsys):
        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            raise subprocess.TimeoutExpired(cmd, timeout or 0)

        monkeypatch.setattr(probe.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv",
                            ["probe.py", "--samples", "0", "--no-recency", "a", "b"])
        with pytest.raises(SystemExit):
            probe.main()
        out = json.loads(capsys.readouterr().out)
        assert out["keywords"] == []
        assert len(out["failed"]) == 2
