"""Tests for the tl-keyword-research search_videos.py script (the trend lane).

Loaded by path; ES is mocked by patching the module's subprocess.run. The fake
answers the article search and the channel-doc enrichment by inspecting the
body it receives.
"""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "search_videos.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_search_videos", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sv = _load()


def _fake_run(video_rows=None, enrich_rows=None, capture=None):
    video_rows = video_rows if video_rows is not None else [
        {"id": "v1", "title": "Fable 5 first look", "url": "https://youtu.be/v1",
         "publication_date": "2026-06-12", "views": 120000, "likes": 8000,
         "duration": 900, "_score": 41.2, "channel": {"id": 2105}},
        {"id": "v2", "title": "Mythos 5 benchmarks", "url": "https://youtu.be/v2",
         "publication_date": "2026-06-14", "views": 45000, "likes": 2100,
         "duration": 780, "_score": 33.0, "channel": {"id": 466311}},
    ]
    enrich_rows = enrich_rows if enrich_rows is not None else [
        {"id": 2105, "name": "AI Explained", "reach": 938000},
        {"id": 466311, "name": "Tech Notes", "reach": 51000},
    ]

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        if capture is not None:
            capture.append(body)
        filters = body["query"]["bool"].get("filter", [])
        is_enrich = any(f.get("term", {}).get("doc_type") == "channel" for f in filters)
        rows = enrich_rows if is_enrich else video_rows
        return subprocess.CompletedProcess(
            cmd, 0, stdout=json.dumps({"results": rows, "total": 3120}), stderr="")

    return run


def _main(monkeypatch, argv, **fake_kwargs):
    monkeypatch.setattr(sv.subprocess, "run", _fake_run(**fake_kwargs))
    monkeypatch.setattr(sv.sys, "argv", ["search_videos.py"] + argv)
    monkeypatch.setattr(sv.sys.stdin, "isatty", lambda: True)  # no stdin keywords
    sv.main()


class TestQueryModes:
    def test_group_mode_sqs_clauses(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--group", '("fable 5" | fable5)',
                            "--group", '("mythos 5" | mythos5) -keto'], capture=bodies)
        clauses = bodies[0]["query"]["bool"]["should"]
        assert [c["simple_query_string"]["query"] for c in clauses] == [
            '("fable 5" | fable5)', '("mythos 5" | mythos5) -keto']
        assert all(c["simple_query_string"]["default_operator"] == "and" for c in clauses)

    def test_group_and_any_conflict(self, monkeypatch):
        monkeypatch.setattr(sv.sys, "argv",
                            ["search_videos.py", "--group", "a", "--any", "b,c"])
        monkeypatch.setattr(sv.sys.stdin, "isatty", lambda: True)
        with pytest.raises(SystemExit):
            sv.main()

    def test_flat_or_default(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing", "stock market"], capture=bodies)
        b = bodies[0]["query"]["bool"]
        assert b["minimum_should_match"] == 1
        assert len(b["should"]) == 2


class TestTrendControls:
    def test_default_sort_is_score_no_collapse(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing"], capture=bodies)
        assert bodies[0]["sort"] == [{"_score": "desc"}]
        assert "collapse" not in bodies[0]

    def test_sort_date_and_window(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--sort", "date", "--since", "2026-06-01", "investing"],
              capture=bodies)
        assert bodies[0]["sort"] == [{"publication_date": "desc"}]
        filters = bodies[0]["query"]["bool"]["filter"]
        assert {"range": {"publication_date": {"gte": "2026-06-01"}}} in filters

    def test_sort_views(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--sort", "views", "investing"], capture=bodies)
        assert bodies[0]["sort"] == [{"views": "desc"}]

    def test_distinct_channels_collapses(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--distinct-channels", "investing"], capture=bodies)
        assert bodies[0]["collapse"] == {"field": "channel.id"}


class TestScope:
    def test_youtube_and_longform_always_on(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing"], capture=bodies)
        filters = bodies[0]["query"]["bool"]["filter"]
        assert {"term": {"doc_type": "article"}} in filters
        assert {"term": {"channel.format": 4}} in filters
        assert {"term": {"content_type": "longform"}} in filters
        out = json.loads(capsys.readouterr().out)
        assert out["scope"] == {"format": "youtube", "content_type": "longform"}

    def test_content_type_all_drops_filter(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["--content-type", "all", "investing"], capture=bodies)
        filters = bodies[0]["query"]["bool"]["filter"]
        assert not any("content_type" in f.get("term", {}) for f in filters)


class TestOutput:
    def test_videos_enriched_with_channel_name_and_subscribers(self, monkeypatch, capsys):
        _main(monkeypatch, ["investing"])
        out = json.loads(capsys.readouterr().out)
        assert out["total_matching_videos"] == 3120
        v = out["videos"][0]
        assert v["video_id"] == "v1"
        assert v["title"] == "Fable 5 first look"
        assert v["views"] == 120000
        assert v["channel"] == {"channel_id": 2105, "name": "AI Explained",
                                "subscribers": 938000}

    def test_enrich_source_pins_legacy_reach(self):
        assert "reach" in sv.ENRICH_SOURCE
        assert "subscribers" not in sv.ENRICH_SOURCE

    def test_enrich_body_collapses_channel_docs(self, monkeypatch, capsys):
        bodies = []
        _main(monkeypatch, ["investing"], capture=bodies)
        assert bodies[1]["collapse"] == {"field": "id"}
        assert bodies[1]["query"]["bool"]["filter"][0] == {"term": {"doc_type": "channel"}}

    def test_groups_expression_rendered(self, monkeypatch, capsys):
        _main(monkeypatch, ["--group", "(a | b)", "--not", "keto"])
        out = json.loads(capsys.readouterr().out)
        assert out["expression"]["expression"] == "((a | b)) AND NOT keto"
        assert out["query"]["mode"] == "groups"
