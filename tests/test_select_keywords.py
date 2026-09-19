"""Tests for select_keywords.py — the inline-verdict apply step.

The script lives under skills/ (not the package), so we load it by path.
"""
import importlib.util
import json
from pathlib import Path

import pytest

_PATH = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts" / "select_keywords.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("kw_select", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


select = _load()


def _sample(video_id, channel_id):
    return {"video_id": video_id, "channel_id": channel_id, "title": f"video {video_id}",
            "date": "2026-06-20", "url": f"https://y/{video_id}", "category": "Marketing",
            "stratum": "title", "field": "title", "snippet": "«x» y"}


PROBE = {
    "operator": "OR",
    "level": "topic",
    "fields": ["title", "summary", "transcript"],
    "keywords": [
        {"keyword": "cannes lions", "mode": "phrase", "documents": 347, "channels": 143,
         "strata": {"title": 63, "summary_only": 235, "transcript_only": 49},
         "transcript_share": 0.14, "signals": [],
         "samples": [_sample(1, 11), _sample(2, 12)],
         "residual": {"vs": "core", "documents": 120, "channels": 61,
                      "samples": [_sample(3, 13)]}},
        {"keyword": "cannes", "mode": "phrase", "documents": 12004, "channels": 5120,
         "strata": {"title": 4100, "summary_only": 6000, "transcript_only": 1904},
         "transcript_share": 0.16, "signals": ["too_broad"], "samples": [_sample(4, 14)]},
        {"keyword": '("young lions" | younglions)', "mode": "sqs", "documents": 90,
         "channels": 40, "strata": {"title": 10, "summary_only": 60, "transcript_only": 20},
         "transcript_share": 0.22, "signals": ["transcript_led"], "samples": [_sample(5, 15)]},
    ],
    "failed": [{"keyword": "lions festival", "reason": "timeout"}],
    "unresolved": [{"keyword": "cannes young lions", "reason": "deadline"}],
}


def _write(tmp_path, name, obj):
    path = tmp_path / name
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _run(monkeypatch, capsys, tmp_path, verdicts, extra=(), probe=None):
    probe_path = _write(tmp_path, "probe.json", probe if probe is not None else PROBE)
    argv = ["select_keywords.py", "--apply", "--probe-file", probe_path]
    for i, v in enumerate(verdicts):
        argv += ["--verdicts", v if isinstance(v, str) else _write(tmp_path, f"v{i}.json", v)]
    argv += list(extra)
    monkeypatch.setattr(select.sys, "argv", argv)
    select.main()
    return json.loads(capsys.readouterr().out)


ALL_KEEP = [
    {"keyword": "cannes lions", "verdict": "keep"},
    {"keyword": "cannes", "verdict": "drop", "exclude_hint": "film festival",
     "note": "film festival dominates"},
    {"keyword": '("young lions" | younglions)', "verdict": "unsure", "note": "mixed"},
]


class TestApply:
    def test_happy_path(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]
        assert out["kept"][0]["mode"] == "phrase"
        assert out["kept"][0]["documents"] == 347 and out["kept"][0]["channels"] == 143
        assert out["kept"][0]["strata"]["transcript_only"] == 49
        assert out["kept"][0]["transcript_share"] == 0.14
        assert out["dropped"] == [{"keyword": "cannes", "reason": "film festival dominates",
                                   "exclude_hint": "film festival"}]
        assert out["unsure"] == [{"keyword": '("young lions" | younglions)', "note": "mixed",
                                  "signals": ["transcript_led"]}]
        assert out["missing"] == []
        assert out["level"] == "topic" and out["operator"] == "OR"

    def test_groups_quote_plain_phrases_and_keep_booleans_verbatim(self, monkeypatch, capsys, tmp_path):
        verdicts = [{"keyword": "cannes lions", "verdict": "keep"},
                    {"keyword": "cannes", "verdict": "drop"},
                    {"keyword": '("young lions" | younglions)', "verdict": "keep"}]
        out = _run(monkeypatch, capsys, tmp_path, [verdicts])
        assert out["groups"] == [{"text": '"cannes lions"'},
                                 {"text": '("young lions" | younglions)'}]

    def test_candidate_channels_and_videos_include_residual_samples(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP])
        assert [v["video_id"] for v in out["candidate_videos"]] == [1, 2, 3]
        assert [c["channel_id"] for c in out["candidate_channels"]] == [11, 12, 13]

    def test_channel_level_targets(self, monkeypatch, capsys, tmp_path):
        probe = {"level": "channel", "operator": "OR", "keywords": [
            {"keyword": "cooking", "mode": "phrase", "documents": 9, "channels": 4, "signals": [],
             "samples": [{"channel_id": 7, "name": "Chef Bob", "topic": "cooking"},
                         {"channel_id": 7, "name": "Chef Bob", "topic": "cooking"}]}]}
        out = _run(monkeypatch, capsys, tmp_path,
                   [[{"keyword": "cooking", "verdict": "keep"}]], probe=probe)
        assert out["candidate_channels"] == [{"channel_id": 7, "name": "Chef Bob",
                                              "topic": "cooking"}]
        assert "candidate_videos" not in out

    def test_fitness_counts(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP])
        assert out["fitness"] == {"candidates": 3, "judged": 3, "kept": 1, "dropped": 1,
                                  "unsure": 1, "missing": 0, "ignored_verdicts": 0,
                                  "transcript_led": 1, "flagged": {"transcript_led": 1}}

    def test_not_probed_lists_failed_and_unresolved(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP])
        assert out["not_probed"] == [{"keyword": "lions festival", "reason": "timeout"},
                                     {"keyword": "cannes young lions", "reason": "deadline"}]

    def test_later_file_overrides_earlier(self, monkeypatch, capsys, tmp_path):
        first = [{"keyword": "cannes lions", "verdict": "drop"},
                 {"keyword": "cannes", "verdict": "drop"},
                 {"keyword": '("young lions" | younglions)', "verdict": "drop"}]
        second = [{"keyword": "cannes lions", "verdict": "keep"}]
        out = _run(monkeypatch, capsys, tmp_path, [first, second])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]
        assert [d["keyword"] for d in out["dropped"]] == ["cannes", '("young lions" | younglions)']

    def test_identical_repeat_in_one_file_is_fine(self, monkeypatch, capsys, tmp_path):
        verdicts = ALL_KEEP + [{"keyword": "cannes lions", "verdict": "keep"}]
        out = _run(monkeypatch, capsys, tmp_path, [verdicts])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]

    def test_stdin_verdicts(self, monkeypatch, capsys, tmp_path):
        path = tmp_path / "v.json"
        path.write_text(json.dumps(ALL_KEEP), encoding="utf-8")
        with open(path, encoding="utf-8") as fh:
            monkeypatch.setattr(select.sys, "stdin", fh)
            out = _run(monkeypatch, capsys, tmp_path, ["-"])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]


class TestValidation:
    def _expect_exit(self, monkeypatch, capsys, tmp_path, verdicts, code=1):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, capsys, tmp_path, [verdicts])
        assert exc.value.code != 0 if code is None else True
        return exc.value

    def test_not_an_array(self, monkeypatch, capsys, tmp_path):
        exc = self._expect_exit(monkeypatch, capsys, tmp_path, {"keyword": "cannes"})
        assert "bare JSON array" in str(exc.code)

    def test_unknown_keyword_is_listed(self, monkeypatch, capsys, tmp_path):
        exc = self._expect_exit(monkeypatch, capsys, tmp_path,
                                ALL_KEEP + [{"keyword": "nope", "verdict": "keep"}])
        assert "nope" in str(exc.code) and "not in the probe file" in str(exc.code)

    def test_bad_verdict_value(self, monkeypatch, capsys, tmp_path):
        exc = self._expect_exit(monkeypatch, capsys, tmp_path,
                                [{"keyword": "cannes lions", "verdict": "maybe"}])
        assert "maybe" in str(exc.code)

    def test_conflicting_duplicate_in_one_file(self, monkeypatch, capsys, tmp_path):
        exc = self._expect_exit(monkeypatch, capsys, tmp_path,
                                [{"keyword": "cannes lions", "verdict": "keep"},
                                 {"keyword": "cannes lions", "verdict": "drop"}])
        assert "two different verdicts" in str(exc.code)

    def test_missing_keyword_field(self, monkeypatch, capsys, tmp_path):
        exc = self._expect_exit(monkeypatch, capsys, tmp_path, [{"verdict": "keep"}])
        assert "'keyword' string" in str(exc.code)


class TestMissingCoverage:
    PARTIAL = [{"keyword": "cannes lions", "verdict": "keep"}]

    def test_missing_exits_2_and_still_prints(self, monkeypatch, capsys, tmp_path):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, capsys, tmp_path, [self.PARTIAL])
        assert exc.value.code == 2
        out = json.loads(capsys.readouterr().out)
        assert out["missing"] == ["cannes", '("young lions" | younglions)']
        assert out["fitness"]["missing"] == 2 and out["fitness"]["judged"] == 1

    def test_allow_missing_exits_0(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [self.PARTIAL], extra=["--allow-missing"])
        assert out["missing"] == ["cannes", '("young lions" | younglions)']
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]


def _write_text(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


TSV_ALL = (
    "# one line per candidate — keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note]\n"
    "\n"
    "cannes lions\tkeep\n"
    "cannes\tdrop\tfilm festival\tfilm festival dominates\n"
    '("young lions" | younglions)\tunsure\t\tmixed\n'
)


class TestTsvVerdicts:
    """Writing 200 JSON objects is the model's slowest step; TSV says the same
    thing in one line each (select_keywords.py parse_tsv_verdicts())."""

    def test_happy_path(self, monkeypatch, capsys, tmp_path):
        path = _write_text(tmp_path, "v.tsv", "cannes lions\tkeep\ncannes\tdrop\n"
                                              '("young lions" | younglions)\tunsure\n')
        out = _run(monkeypatch, capsys, tmp_path, [path])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]
        assert [d["keyword"] for d in out["dropped"]] == ["cannes"]
        assert [u["keyword"] for u in out["unsure"]] == ['("young lions" | younglions)']
        assert out["missing"] == []

    def test_hint_note_comments_and_blank_lines(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [_write_text(tmp_path, "v.tsv", TSV_ALL)])
        assert out["kept"][0]["keyword"] == "cannes lions"
        assert out["dropped"] == [{"keyword": "cannes", "reason": "film festival dominates",
                                   "exclude_hint": "film festival"}]
        assert out["unsure"][0]["note"] == "mixed"          # empty hint column skipped

    def test_bad_verdict_names_the_line(self, monkeypatch, capsys, tmp_path):
        path = _write_text(tmp_path, "v.tsv", "# header\n\ncannes lions\tkeep\n"
                                              "cannes\tmaybe\n")
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, capsys, tmp_path, [path])
        assert "line 4" in str(exc.value.code) and "maybe" in str(exc.value.code)

    def test_short_line_names_the_line(self, monkeypatch, capsys, tmp_path):
        path = _write_text(tmp_path, "v.tsv", "cannes lions\n")
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, capsys, tmp_path, [path])
        assert "line 1" in str(exc.value.code)

    def test_json_and_tsv_files_mix(self, monkeypatch, capsys, tmp_path):
        first = _write(tmp_path, "v0.json", [{"keyword": "cannes lions", "verdict": "drop"},
                                             {"keyword": "cannes", "verdict": "drop"}])
        second = _write_text(tmp_path, "v1.tsv",
                             'cannes lions\tkeep\n("young lions" | younglions)\tkeep\n')
        out = _run(monkeypatch, capsys, tmp_path, [first, second])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions",
                                                       '("young lions" | younglions)']
        assert [d["keyword"] for d in out["dropped"]] == ["cannes"]   # TSV overrode the JSON

    def test_stdin_tsv(self, monkeypatch, capsys, tmp_path):
        path = tmp_path / "v.tsv"
        path.write_text("cannes lions\tkeep\ncannes\tdrop\n"
                        '("young lions" | younglions)\tdrop\n', encoding="utf-8")
        with open(path, encoding="utf-8") as fh:
            monkeypatch.setattr(select.sys, "stdin", fh)
            out = _run(monkeypatch, capsys, tmp_path, ["-"])
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]


PROBE_WITH_DROPPED = {
    **PROBE,
    "dropped": [{"keyword": "lions week", "count": 0, "reason": "no_matches",
                 "signals": ["empty"]}],
}


class TestIgnoredVerdicts:
    """A verdict for a candidate the probe dropped/failed/never reached is not an
    error — the sheet showed it. Only a keyword the probe never saw is fatal."""

    def _verdicts(self, *extra):
        return ALL_KEEP + list(extra)

    def test_dropped_failed_and_unresolved_keywords_are_ignored(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path,
                   [self._verdicts({"keyword": "lions week", "verdict": "keep"},
                                   {"keyword": "lions festival", "verdict": "drop"},
                                   {"keyword": "cannes young lions", "verdict": "unsure"})],
                   probe=PROBE_WITH_DROPPED)
        assert out["ignored_verdicts"] == [
            {"keyword": "lions week", "why": "dropped"},
            {"keyword": "lions festival", "why": "failed"},
            {"keyword": "cannes young lions", "why": "unresolved"}]
        assert out["fitness"]["ignored_verdicts"] == 3
        assert [k["keyword"] for k in out["kept"]] == ["cannes lions"]
        assert [d["keyword"] for d in out["dropped"]] == ["cannes"]  # not the 0-doc one
        assert out["missing"] == []

    def test_a_keyword_the_probe_never_saw_is_still_fatal(self, monkeypatch, capsys, tmp_path):
        with pytest.raises(SystemExit) as exc:
            _run(monkeypatch, capsys, tmp_path,
                 [self._verdicts({"keyword": "nope", "verdict": "keep"})],
                 probe=PROBE_WITH_DROPPED)
        assert "nope" in str(exc.value.code) and "not in the probe file" in str(exc.value.code)

    def test_ignored_is_empty_by_default(self, monkeypatch, capsys, tmp_path):
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP])
        assert out["ignored_verdicts"] == []

    def test_ignored_in_tsv_too(self, monkeypatch, capsys, tmp_path):
        path = _write_text(tmp_path, "v.tsv",
                           "cannes lions\tkeep\ncannes\tdrop\n"
                           '("young lions" | younglions)\tdrop\nlions week\tdrop\n')
        out = _run(monkeypatch, capsys, tmp_path, [path], probe=PROBE_WITH_DROPPED)
        assert out["ignored_verdicts"] == [{"keyword": "lions week", "why": "dropped"}]


class TestUnionRow:
    """probe.py's synthetic `union` row measures the whole filter — it is a
    measurement, not a candidate, so it needs no verdict."""

    def test_union_row_is_not_missing(self, monkeypatch, capsys, tmp_path):
        probe = {**PROBE, "keywords": PROBE["keywords"] + [
            {"keyword": "(a) | (b)", "mode": "groups", "documents": 900, "channels": 300,
             "signals": [], "samples": [], "union": True}]}
        out = _run(monkeypatch, capsys, tmp_path, [ALL_KEEP], probe=probe)
        # the union is a measurement, not a candidate: excluding it keeps
        # judged + missing + ignored == candidates
        assert out["missing"] == [] and out["fitness"]["candidates"] == 3
        f = out["fitness"]
        assert f["judged"] + f["missing"] + f["ignored_verdicts"] == f["candidates"]


class TestTsvBoundedSplit:
    def test_the_last_column_keeps_its_embedded_tabs(self, monkeypatch, capsys, tmp_path):
        path = _write_text(tmp_path, "v.tsv",
                           "cannes lions\tkeep\n"
                           "cannes\tdrop\tfilm festival\ttoo broad\there\n"
                           '("young lions" | younglions)\tkeep\n')
        out = _run(monkeypatch, capsys, tmp_path, [path])
        assert out["dropped"] == [{"keyword": "cannes", "reason": "too broad\there",
                                   "exclude_hint": "film festival"}]
