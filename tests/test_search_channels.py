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
