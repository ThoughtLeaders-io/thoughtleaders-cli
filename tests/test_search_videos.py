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
    monkeypatch.setattr(sv.kw_common.subprocess, "run", _fake_run(**fake_kwargs))
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
        assert out["scope"] == {"format": "youtube", "content_type": "longform",
                                "since": None, "until": None}

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


class TestRunLedger:
    def test_event_records_a_numeric_elapsed(self, monkeypatch, tmp_path, capsys):
        _main(monkeypatch, ["--run-dir", str(tmp_path), "--no-enrich", "fable 5"])
        capsys.readouterr()
        events = sorted((tmp_path / "events").glob("*.json"))
        assert len(events) == 1
        event = json.loads(events[0].read_text(encoding="utf-8"))
        assert event["script"] == "search_videos"
        assert isinstance(event["elapsed_seconds"], (int, float))


class TestChannelIdentityAndSheet:
    def test_channel_fields_are_top_level(self, monkeypatch, capsys):
        _main(monkeypatch, ["investing"])
        out = json.loads(capsys.readouterr().out)
        first = out["videos"][0]
        assert (first["channel_id"], first["channel_name"], first["subscribers"]) == (
            2105, "AI Explained", 938000)
        assert first["channel"] == {"channel_id": 2105, "name": "AI Explained",
                                    "subscribers": 938000}

    def test_enrichment_joins_when_channel_doc_ids_are_strings(self, monkeypatch, capsys):
        _main(monkeypatch, ["investing"], enrich_rows=[
            {"id": "2105", "name": "AI Explained", "reach": 938000},
            {"id": "466311", "name": "Tech Notes", "reach": 51000}])
        out = json.loads(capsys.readouterr().out)
        assert [v["channel_name"] for v in out["videos"]] == ["AI Explained", "Tech Notes"]

    def test_channel_name_from_the_video_doc_without_enrichment(self, monkeypatch, capsys):
        _main(monkeypatch, ["--no-enrich", "investing"], video_rows=[
            {"id": "v1", "title": "T", "url": "u", "publication_date": "2026-06-12",
             "views": 900, "channel": {"id": 2105, "channel_name": "AI Explained"}}])
        out = json.loads(capsys.readouterr().out)
        assert out["videos"][0]["channel_name"] == "AI Explained"

    def test_sheet_is_one_line_per_video(self, monkeypatch, capsys, tmp_path):
        sheet = tmp_path / "videos.md"
        _main(monkeypatch, ["--sort", "date", "--since", "2025-09-19",
                            "--sheet", str(sheet), "investing"])
        lines = sheet.read_text(encoding="utf-8").splitlines()
        assert lines[0] == ("# Videos · date · youtube longform · 2025-09-19.. · "
                            "3120 matching · showing 2")
        assert lines[1] == "- 2026-06-12 · 120K views · AI Explained (2105) · Fable 5 first look"
        assert lines[2] == "- 2026-06-14 · 45K views · Tech Notes (466311) · Mythos 5 benchmarks"

    def test_sheet_compacts_millions_and_truncates_the_title(self, monkeypatch, capsys, tmp_path):
        sheet = tmp_path / "videos.md"
        _main(monkeypatch, ["--sheet", str(sheet), "investing"], video_rows=[
            {"id": "v1", "title": "x" * 200, "url": "u", "publication_date": "2026-03-08",
             "views": 32614254, "channel": {"id": 2105}}])
        row = sheet.read_text(encoding="utf-8").splitlines()[1]
        assert "32.6M views" in row
        assert row.endswith("…") and len(row.split(" · ")[-1]) == 90


class TestArgvParsing:
    """Positionals may appear anywhere (parse_intermixed_args); a mistyped flag
    is named rather than searched for as a keyword."""

    def test_keywords_after_options_are_parsed(self, monkeypatch, capsys):
        _main(monkeypatch, ["--no-enrich", "fable 5", "--size", "5", "mythos 5"])
        out = json.loads(capsys.readouterr().out)
        assert out["query"]["keywords"] == ["fable 5", "mythos 5"]

    def test_mistyped_option_is_rejected_by_name(self, monkeypatch, capsys):
        monkeypatch.setattr(sv.sys, "argv",
                            ["search_videos.py", "--sinse", "2026-01-01", "fable 5"])
        monkeypatch.setattr(sv.sys.stdin, "isatty", lambda: True)
        with pytest.raises(SystemExit):
            sv.main()
        assert "--sinse" in capsys.readouterr().err


class TestDeadline:
    """An expired budget is not an error: exiting non-zero would break the `&&`
    chain the skill runs these steps in."""

    def test_empty_envelope_exit_zero_and_a_one_line_sheet(self, monkeypatch, capsys,
                                                           tmp_path):
        sheet = tmp_path / "videos.md"
        calls = []
        _main(monkeypatch, ["fable 5", "--no-enrich", "--sheet", str(sheet),
                            "--deadline-at", "1"], capture=calls)
        out = json.loads(capsys.readouterr().out)
        assert out["videos"] == [] and out["total_matching_videos"] == 0
        assert out["unresolved"] == "deadline"
        assert out["query"]["keywords"] == ["fable 5"]
        assert calls == []                                  # ES was never called
        assert sheet.read_text(encoding="utf-8") == "deadline reached — not run\n"
