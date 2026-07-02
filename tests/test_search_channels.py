"""Tests for the tl-keyword-research search_channels.py script.

Loaded by path (it lives under skills/, not the package); ES is mocked by
patching the module's subprocess.run. The fake answers the collapsed article
search and the channel-doc enrichment by inspecting the body it receives.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "search_channels.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_search_channels", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load()


def _fake_run(search_rows=None, enrich_rows=None, capture=None):
    """subprocess.run stand-in. `capture` (a list) collects every ES body."""
    search_rows = search_rows if search_rows is not None else [
        {"channel": {"id": 2105}, "_score": 55.4, "_id": "v1", "title": "Stocks 101"},
    ]
    enrich_rows = enrich_rows if enrich_rows is not None else [
        {"id": 2105, "name": "Financial Education", "is_active": True,
         "is_tl_channel": True, "media_selling_network_join_date": None,
         "has_outreach_email": True, "sponsorship_price": 4710.0, "reach": 938000},
    ]

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        if capture is not None:
            capture.append(body)
        filters = body["query"]["bool"].get("filter", [])
        is_enrich = any(f.get("term", {}).get("doc_type") == "channel" for f in filters)
        rows = enrich_rows if is_enrich else search_rows
        payload = {"results": rows, "total": 312}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    return run


def _main(monkeypatch, argv, **fake_kwargs):
    monkeypatch.setattr(sc.subprocess, "run", _fake_run(**fake_kwargs))
    monkeypatch.setattr(sc.sys, "argv", ["search_channels.py"] + argv)
    monkeypatch.setattr(sc.sys.stdin, "isatty", lambda: True)  # no stdin keywords
    sc.main()


class TestGroupMode:
    def test_groups_are_sqs_clauses_with_and_default(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--group", '("fable 5" | fable5)',
                            "--group", '("mythos 5" | mythos5) -keto'], capture=bodies)
        search = bodies[0]["query"]["bool"]
        clauses = search["should"]
        assert search["minimum_should_match"] == 1
        assert [c["simple_query_string"]["query"] for c in clauses] == [
            '("fable 5" | fable5)', '("mythos 5" | mythos5) -keto']
        assert all(c["simple_query_string"]["default_operator"] == "and" for c in clauses)

    def test_operator_and_puts_groups_in_must(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--operator", "AND", "--group", "a", "--group", "b"],
              capture=bodies)
        assert "must" in bodies[0]["query"]["bool"]
        assert "should" not in bodies[0]["query"]["bool"]

    def test_positional_keywords_become_phrase_groups(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--group", "(a | b)", "tiktok shop"], capture=bodies)
        queries = [c["simple_query_string"]["query"]
                   for c in bodies[0]["query"]["bool"]["should"]]
        assert '"tiktok shop"' in queries

    def test_group_and_any_conflict(self, monkeypatch):
        monkeypatch.setattr(sc.sys, "argv",
                            ["search_channels.py", "--group", "a", "--any", "b,c"])
        monkeypatch.setattr(sc.sys.stdin, "isatty", lambda: True)
        with pytest.raises(SystemExit):
            sc.main()

    def test_groups_expression_rendered(self, monkeypatch, capsys):
        _main(monkeypatch, ["--group", '("fable 5" | fable5)', "--group", "claude",
                            "--not", "keto"])
        out = json.loads(capsys.readouterr().out)
        assert out["query"]["mode"] == "groups"
        assert out["expression"]["expression"] == \
            '(("fable 5" | fable5)) OR (claude) AND NOT keto'
        assert out["expression"]["groups"] == ['("fable 5" | fable5)', "claude"]
        assert out["cnf"] == out["expression"]  # back-compat alias


class TestScope:
    def test_youtube_and_longform_always_on(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing"], capture=bodies)
        filters = bodies[0]["query"]["bool"]["filter"]
        assert {"term": {"channel.format": 4}} in filters
        assert {"term": {"content_type": "longform"}} in filters
        out = json.loads(capsys.readouterr().out)
        assert out["scope"] == {"format": "youtube", "content_type": "longform"}

    def test_content_type_all_drops_filter(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--content-type", "all", "investing"], capture=bodies)
        filters = bodies[0]["query"]["bool"]["filter"]
        assert {"term": {"channel.format": 4}} in filters
        assert not any("content_type" in f.get("term", {}) for f in filters)

    def test_composed_mode_also_scoped(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--any", "a,b", "--any", "c"], capture=bodies)
        assert {"term": {"channel.format": 4}} in bodies[0]["query"]["bool"]["filter"]


class TestEnrichment:
    def test_sponsorability_translates_legacy_es_names(self, monkeypatch, capsys):
        # ES channel docs keep the pre-rename names (reach, is_tl_channel);
        # output speaks the new vocabulary (subscribers, is_tpp).
        _main(monkeypatch, ["investing"])
        out = json.loads(capsys.readouterr().out)
        sp = out["channels"][0]["sponsorability"]
        assert sp["subscribers"] == 938000
        assert sp["is_tpp"] is True
        assert "reach" not in sp and "is_tl_channel" not in sp

    def test_enrich_source_pins_legacy_field_names(self):
        assert "reach" in sc.ENRICH_SOURCE
        assert "is_tl_channel" in sc.ENRICH_SOURCE
        assert "subscribers" not in sc.ENRICH_SOURCE
        assert "is_tpp" not in sc.ENRICH_SOURCE

    def test_both_collapses(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing"], capture=bodies)
        assert bodies[0]["collapse"] == {"field": "channel.id"}   # search: one row per channel
        assert bodies[1]["collapse"] == {"field": "id"}           # enrich: one doc per id


class TestRenderCnf:
    def test_flat_or(self):
        got = sc.render_cnf([["investing", "stock market"]], ["sermon"])
        assert got["expression"] == '(investing OR "stock market") AND (NOT sermon)'

    def test_composed(self):
        got = sc.render_cnf([["a", "b"], ["c"]], [])
        assert got["expression"] == "(a OR b) AND (c)"


def _fake_run_intensity(buckets=None, totals=None, enrich_rows=None, capture=None):
    """Fake for --intensity: answers the agg call, the totals call, and enrichment."""
    buckets = buckets if buckets is not None else [
        {"key": 1, "doc_count": 12, "recent": {"doc_count": 5}},   # core candidate
        {"key": 2, "doc_count": 4, "recent": {"doc_count": 0}},    # recurring
        {"key": 3, "doc_count": 2, "recent": {"doc_count": 2}},    # occasional
        {"key": 4, "doc_count": 1, "recent": {"doc_count": 1}},    # one_off
    ]
    totals = totals if totals is not None else {1: 20, 2: 400, 3: 50, 4: 900}
    enrich_rows = enrich_rows if enrich_rows is not None else [
        {"id": k, "name": f"ch{k}", "reach": 1000 * k, "is_tl_channel": False}
        for k in totals
    ]

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        if capture is not None:
            capture.append(body)
        filters = body["query"]["bool"].get("filter", [])
        if any(f.get("term", {}).get("doc_type") == "channel" for f in filters):
            payload = {"results": enrich_rows, "total": len(enrich_rows)}
        elif any("terms" in f and "channel.id" in f.get("terms", {}) for f in filters):
            payload = {"results": [], "total": sum(totals.values()), "aggregations": {
                "by_channel": {"buckets": [
                    {"key": k, "doc_count": v} for k, v in totals.items()]}}}
        else:
            payload = {"results": [], "total": 19, "aggregations": {
                "distinct_channels": {"value": 433},
                "by_channel": {"buckets": buckets}}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

    return run


class TestIntensityMode:
    def _run(self, monkeypatch, argv, **kw):
        monkeypatch.setattr(sc.subprocess, "run", _fake_run_intensity(**kw))
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py"] + argv)
        monkeypatch.setattr(sc.sys.stdin, "isatty", lambda: True)
        sc.main()

    def test_one_agg_call_shape(self, monkeypatch, capsys):
        bodies = []
        self._run(monkeypatch, ["--intensity", "--top", "150",
                                "--group", '("cannes lions" | canneslions)'], capture=bodies)
        agg = bodies[0]
        assert agg["size"] == 0
        assert agg["aggs"]["by_channel"]["terms"] == {"field": "channel.id", "size": 150}
        assert "range" in agg["aggs"]["by_channel"]["aggs"]["recent"]["filter"]
        assert agg["aggs"]["distinct_channels"] == {"cardinality": {"field": "channel.id"}}
        # scope still applies to the agg query
        assert {"term": {"channel.format": 4}} in agg["query"]["bool"]["filter"]

    def test_tiers_and_share(self, monkeypatch, capsys):
        self._run(monkeypatch, ["--intensity", "investing"])
        out = json.loads(capsys.readouterr().out)
        by_id = {c["channel_id"]: c for c in out["channels"]}
        assert by_id[1]["tier"] == "core"          # 12/20 = 0.6 share
        assert by_id[1]["topic_share"] == 0.6
        assert by_id[2]["tier"] == "recurring"     # 4 matches, 1% share
        assert by_id[3]["tier"] == "occasional"    # 2 matches
        assert by_id[4]["tier"] == "one_off"       # 1 match
        assert out["tiers"] == {"core": 1, "recurring": 1, "occasional": 1, "one_off": 1}
        assert out["distinct_channels"] == 433
        assert by_id[1]["recent_matching_uploads"] == 5

    def test_no_share_skips_totals_call(self, monkeypatch, capsys):
        bodies = []
        self._run(monkeypatch, ["--intensity", "--no-share", "investing"], capture=bodies)
        out = json.loads(capsys.readouterr().out)
        # agg call + enrichment only — no totals call
        assert len(bodies) == 2
        by_id = {c["channel_id"]: c for c in out["channels"]}
        assert by_id[1]["topic_share"] is None
        assert by_id[1]["tier"] == "recurring"     # no share → can't be core

    def test_enrichment_and_order(self, monkeypatch, capsys):
        self._run(monkeypatch, ["--intensity", "investing"])
        out = json.loads(capsys.readouterr().out)
        assert [c["channel_id"] for c in out["channels"]] == [1, 2, 3, 4]  # biggest first
        assert out["channels"][0]["name"] == "ch1"
        assert out["channels"][0]["sponsorability"]["subscribers"] == 1000

    def test_recurring_min_flag(self, monkeypatch, capsys):
        self._run(monkeypatch, ["--intensity", "--recurring-min", "5", "--no-share", "investing"])
        out = json.loads(capsys.readouterr().out)
        by_id = {c["channel_id"]: c for c in out["channels"]}
        assert by_id[1]["tier"] == "recurring"     # 12 >= 5
        assert by_id[2]["tier"] == "occasional"    # 4 < 5


class TestIntensityTierFn:
    def test_matrix(self):
        assert sc.intensity_tier(1, None, 3, 0.5) == "one_off"
        assert sc.intensity_tier(2, 0.9, 3, 0.5) == "occasional"   # share irrelevant below min
        assert sc.intensity_tier(3, None, 3, 0.5) == "recurring"
        assert sc.intensity_tier(10, 0.49, 3, 0.5) == "recurring"
        assert sc.intensity_tier(10, 0.5, 3, 0.5) == "core"

    def test_string_agg_keys_coerced_for_enrichment(self, monkeypatch, capsys):
        # Terms-agg keys on channel.id come back as STRINGS; channel docs carry
        # numeric ids — without coercion, enrichment and share joins silently miss.
        buckets = [{"key": "1", "doc_count": 12, "recent": {"doc_count": 5}}]
        totals = {"1": 20}

        def run(cmd, input=None, capture_output=None, text=None, timeout=None):
            body = json.loads(input)
            filters = body["query"]["bool"].get("filter", [])
            if any(f.get("term", {}).get("doc_type") == "channel" for f in filters):
                payload = {"results": [{"id": 1, "name": "ch1", "reach": 5000}], "total": 1}
            elif any("terms" in f and "channel.id" in f.get("terms", {}) for f in filters):
                payload = {"results": [], "total": 20, "aggregations": {
                    "by_channel": {"buckets": [{"key": k, "doc_count": v} for k, v in totals.items()]}}}
            else:
                payload = {"results": [], "total": 12, "aggregations": {
                    "distinct_channels": {"value": 1},
                    "by_channel": {"buckets": buckets}}}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")

        monkeypatch.setattr(sc.subprocess, "run", run)
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "investing"])
        monkeypatch.setattr(sc.sys.stdin, "isatty", lambda: True)
        sc.main()
        out = json.loads(capsys.readouterr().out)
        c = out["channels"][0]
        assert c["channel_id"] == 1                 # coerced to int
        assert c["name"] == "ch1"                   # enrichment joined
        assert c["topic_share"] == 0.6              # share joined (12/20)
        assert c["tier"] == "core"
