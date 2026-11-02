"""Library contract of the tl-keyword-research scripts.

Another Python program loads probe.py, select_keywords.py, expand_entities.py and
build_report.py by path and calls their functions directly, while every CLI user keeps
running them as `python3 <script>`. So: the library call must return exactly what the
command prints, bad input must be a typed ValueError on the library path and a non-zero
exit on the command path, and the modules must stay import-safe (standard library only,
no side effects at import, no process I/O outside the command layer).
"""

import ast
import copy
import importlib.util
import io
import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "tl-keyword-research" / "scripts"
_NAMES = ["probe", "select_keywords", "expand_entities", "build_report"]


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kw_lib_{name}", _SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


probe = _load("probe")
sk = _load("select_keywords")
ee = _load("expand_entities")
br = _load("build_report")


def _exit_status(exc):
    """The process exit status a SystemExit produces."""
    if exc.code is None:
        return 0
    return exc.code if isinstance(exc.code, int) else 1


def _cli(mod, monkeypatch, capsys, argv, stdin=""):
    """Run mod.main() as the command would; return (exit status, stdout, stderr)."""
    monkeypatch.setattr(sys, "argv", [mod.__name__, *argv])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    status = 0
    try:
        mod.main()
    except SystemExit as exc:
        status = _exit_status(exc)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def _silent(capsys, fn, *args, **kwargs):
    """Call a library function and assert it printed nothing."""
    result = fn(*args, **kwargs)
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "")
    return result


def _scribble(obj):
    """Mutate every list and dict reachable from obj (a hostile consumer of a returned value)."""
    if isinstance(obj, dict):
        for v in list(obj.values()):
            _scribble(v)
        obj["__scribble__"] = True
    elif isinstance(obj, list):
        for v in list(obj):
            _scribble(v)
        obj.append("__scribble__")


def _forbid_subprocess(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("subprocess.run must not be reached")

    monkeypatch.setattr(subprocess, "run", boom)


# --------------------------------------------------------------------------- probe


def _term_of(body):
    must = body["query"]["bool"]["must"][0]
    if "multi_match" in must:
        return must["multi_match"]["query"]
    return must["simple_query_string"]["query"]


_TOPIC_SAMPLES = {
    "tiktok shop": [
        {"title": "Selling on TikTok Shop", "summary": "guide", "channel": {"id": 1, "content_category": 7}, "url": "u1"},
        {"title": "TikTok Shop tips", "summary": "more", "channel": {"id": 2, "content_category": 7}, "url": "u2"},
    ],
    "tiktok": [{"title": "Dances", "summary": "lol", "channel": {"id": 3, "content_category": 2}, "url": "u3"}],
}
_CHANNEL_SAMPLES = {
    "cooking": [{"name": "Chef Bob", "ai": {"topic_descriptions": "recipes", "description": "d"}, "id": 10}],
    "baking": [{"name": "Bread Co", "ai": {"topic_descriptions": "bread"}, "id": 11}],
}
_COUNTS = {
    "tiktok shop": 60000,
    "tiktok": 40000000,
    "rugpull-xyz": 0,
    "cooking": 900,
    "baking": 40,
    "a +b": 12,
    "c": 3,
    '"tiktok shop" +amazon': 77,
    "crypto": 10,
}
_DISTINCT = {"tiktok shop": 800, "tiktok": 90000, "cooking": 500, "baking": 30, "a +b": 4, "c": 2, '"tiktok shop" +amazon': 20, "crypto": 5}
_RECENT = {"tiktok shop": [4000, 300], "tiktok": [9000, 2], '"tiktok shop" +amazon': [10, 1], "crypto": [1, 1]}
_ACTIVE = {"cooking": 400, "baking": 2}


def _fake_es(timeouts=()):
    """A query function answering by the searched term; `.calls` records every body."""
    calls = []

    def es(body):
        calls.append(body)
        term = _term_of(body)
        if term in timeouts:
            raise probe.ProbeError(f"timed out after {probe.PROBE_TIMEOUT}s")
        rows = {**_TOPIC_SAMPLES, **_CHANNEL_SAMPLES}.get(term, [])
        payload = {"results": rows[: body.get("size", 0)], "total": _COUNTS.get(term, 0)}
        aggs = {"distinct_channels": {"value": _DISTINCT.get(term, 0)}}
        if "recent_window" in body["aggs"]:
            docs, chans = _RECENT.get(term, [0, 0])
            aggs["recent_window"] = {"doc_count": docs, "recent_channels": {"value": chans}}
        if "active_window" in body["aggs"]:
            aggs["active_window"] = {"active_channels": {"value": _ACTIVE.get(term, 0)}}
        payload["aggregations"] = aggs
        return payload

    es.calls = calls
    return es


def _patch_subprocess_with(monkeypatch, es, timeouts=()):
    """Route the command's `tl db es` subprocess to the same fake the library path gets."""

    def run(cmd, input=None, capture_output=None, text=None, timeout=None):
        body = json.loads(input)
        if _term_of(body) in timeouts:
            raise subprocess.TimeoutExpired(cmd, timeout or 0)
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(es(body)), stderr="")

    monkeypatch.setattr(subprocess, "run", run)


_PROBE_CASES = {
    "topic-defaults": (
        ["--samples", "2", "tiktok shop", "rugpull-xyz", "tiktok"],
        "",
        ["tiktok shop", "rugpull-xyz", "tiktok"],
        dict(fields=probe.TOPIC_FIELDS, samples=2),
        (),
    ),
    "channel-level": (
        ["--level", "channel", "--samples", "1", "cooking", "baking"],
        "",
        ["cooking", "baking"],
        dict(fields=probe.CHANNEL_FIELDS, level="channel", samples=1),
        (),
    ),
    "sqs-and-window": (
        [
            "--mode",
            "sqs",
            "--operator",
            "AND",
            "--no-recency",
            "--since",
            "2025-01-01",
            "--until",
            "2025-06-30",
            "--content-type",
            "all",
            "--samples",
            "0",
            "a +b",
            "c",
        ],
        "",
        ["a +b", "c"],
        dict(
            fields=probe.TOPIC_FIELDS,
            mode="sqs",
            operator="AND",
            recency=False,
            since="2025-01-01",
            until="2025-06-30",
            content_type="all",
            samples=0,
        ),
        (),
    ),
    "custom-fields-and-thresholds": (
        [
            "--fields",
            "title^3,summary",
            "--recency-months",
            "6",
            "--min-recent-channels",
            "1",
            "--min-recent-share",
            "0.5",
            "--samples",
            "1",
            "tiktok shop",
            "tiktok",
        ],
        "",
        ["tiktok shop", "tiktok"],
        dict(fields=["title^3", "summary"], recency_months=6, min_recent_channels=1, min_recent_share=0.5, samples=1),
        (),
    ),
    "dict-candidates-on-stdin": (
        ["--samples", "0"],
        json.dumps([{"label": "shop+amazon", "sqs": '"tiktok shop" +amazon'}, "tiktok"]),
        [{"label": "shop+amazon", "sqs": '"tiktok shop" +amazon'}, "tiktok"],
        dict(fields=probe.TOPIC_FIELDS, samples=0),
        (),
    ),
    "one-candidate-times-out": (
        ["--samples", "0", "crypto", "heavy term"],
        "",
        ["crypto", "heavy term"],
        dict(fields=probe.TOPIC_FIELDS, samples=0),
        ("heavy term",),
    ),
}


class TestProbeParity:
    """Library callers rely on run_probe returning exactly what the command prints."""

    @pytest.mark.parametrize("case", list(_PROBE_CASES))
    def test_run_probe_equals_command_output(self, case, monkeypatch, capsys):
        argv, stdin, candidates, kwargs, timeouts = _PROBE_CASES[case]
        lib = _silent(capsys, probe.run_probe, candidates, run_es=_fake_es(timeouts), **kwargs)

        _patch_subprocess_with(monkeypatch, _fake_es(timeouts), timeouts)
        status, out, err = _cli(probe, monkeypatch, capsys, argv, stdin)

        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False) + "\n"
        # the command reports each failed candidate on stderr, one line each
        assert len(err.splitlines()) == len(lib["failed"])
        for failure in lib["failed"]:
            assert failure["keyword"] in err

    def test_every_candidate_failing_is_data_in_the_library_and_exit_1_in_the_command(self, monkeypatch, capsys):
        timeouts = ("a", "b")
        lib = _silent(capsys, probe.run_probe, ["a", "b"], run_es=_fake_es(timeouts), fields=probe.TOPIC_FIELDS, samples=0)
        assert lib["keywords"] == [] and lib["dropped"] == []
        assert [f["keyword"] for f in lib["failed"]] == ["a", "b"]

        _patch_subprocess_with(monkeypatch, _fake_es(timeouts), timeouts)
        status, out, _ = _cli(probe, monkeypatch, capsys, ["--samples", "0", "a", "b"])
        assert status == 1
        assert json.loads(out) == lib  # the JSON is still printed before the failing exit


class TestProbeLibrary:
    def test_fields_is_required(self):
        with pytest.raises(TypeError):
            probe.run_probe(["crypto"], run_es=_fake_es())

    def test_run_es_is_required(self):
        with pytest.raises(TypeError):
            probe.run_probe(["crypto"], fields=probe.TOPIC_FIELDS)

    def test_injected_run_es_replaces_the_subprocess_path(self, monkeypatch):
        _forbid_subprocess(monkeypatch)
        es = _fake_es()
        out = probe.run_probe(["tiktok shop", "tiktok"], run_es=es, fields=probe.TOPIC_FIELDS)
        assert len(es.calls) == 2
        assert [k["keyword"] for k in out["keywords"]] == ["tiktok", "tiktok shop"]

    def test_fields_are_searched_and_echoed_exactly(self):
        es = _fake_es()
        out = probe.run_probe(["tiktok shop"], run_es=es, fields=["title^3", "summary"])
        assert out["fields"] == ["title^3", "summary"]
        assert es.calls[0]["query"]["bool"]["must"][0]["multi_match"]["fields"] == ["title^3", "summary"]

    @pytest.mark.parametrize("requested, sent", [(999, probe.MAX_SAMPLES), (-3, 0)])
    def test_samples_are_clamped(self, requested, sent):
        es = _fake_es()
        probe.run_probe(["tiktok shop"], run_es=es, fields=probe.TOPIC_FIELDS, samples=requested)
        assert es.calls[0]["size"] == sent

    @pytest.mark.parametrize("failure", [RuntimeError("boom"), ValueError(), KeyError("x")])
    def test_any_exception_from_run_es_is_recorded_not_raised(self, failure):
        def es(body):
            if _term_of(body) == "bad":
                raise failure
            return {"results": [], "total": 5}

        out = probe.run_probe(["ok", "bad"], run_es=es, fields=probe.TOPIC_FIELDS, recency=False)
        assert [f["keyword"] for f in out["failed"]] == ["bad"]
        assert out["failed"][0]["error"]
        assert [k["keyword"] for k in out["keywords"]] == ["ok"]


# (id, library kwargs overriding the defaults, candidates, command argv, command stdin)
_BAD_PROBE_INPUT = [
    (
        "date-window-at-channel-level",
        dict(level="channel", since="2025-01-01", fields=probe.CHANNEL_FIELDS),
        ["cooking"],
        ["--level", "channel", "--since", "2025-01-01", "cooking"],
        "",
    ),
    ("malformed-date", dict(since="01-01-2025"), ["crypto"], ["--since", "01-01-2025", "crypto"], ""),
    ("invalid-field-path", dict(fields=["title", "bad field!"]), ["crypto"], ["--fields", "title,bad field!", "crypto"], ""),
    ("no-fields", dict(fields=[]), ["crypto"], ["--fields", ",", "crypto"], ""),
    ("recency-window-below-one", dict(recency_months=0), ["crypto"], ["--recency-months", "0", "crypto"], ""),
    ("no-candidates", dict(), [], [], ""),
    ("candidate-object-without-a-value", dict(), [{"foo": 1}], [], json.dumps([{"foo": 1}])),
    ("unknown-level", dict(level="videos"), ["crypto"], ["--level", "videos", "crypto"], ""),
]


class TestProbeBadInput:
    @pytest.mark.parametrize("case", _BAD_PROBE_INPUT, ids=[c[0] for c in _BAD_PROBE_INPUT])
    def test_library_raises_typed_error_and_command_exits_nonzero(self, case, monkeypatch, capsys):
        _, overrides, candidates, argv, stdin = case
        _forbid_subprocess(monkeypatch)
        es = _fake_es()
        kwargs = {"fields": probe.TOPIC_FIELDS, **overrides}

        with pytest.raises(probe.ProbeInputError):
            probe.run_probe(candidates, run_es=es, **kwargs)
        assert es.calls == []  # input is refused before any query is made

        status, out, _ = _cli(probe, monkeypatch, capsys, argv, stdin)
        assert status != 0
        assert out == ""

    def test_the_typed_error_is_a_value_error(self):
        assert issubclass(probe.ProbeInputError, ValueError)

    def test_a_bare_string_is_not_a_candidate_list(self):
        with pytest.raises(probe.ProbeInputError):
            probe.run_probe("crypto", run_es=_fake_es(), fields=probe.TOPIC_FIELDS)

    def test_stdin_that_is_not_a_list_exits_nonzero(self, monkeypatch, capsys):
        _forbid_subprocess(monkeypatch)
        status, out, _ = _cli(probe, monkeypatch, capsys, [], stdin='{"a": 1}')
        assert status != 0 and out == ""


class TestProbeSharesNothingWithModuleState:
    """The loaded module serves many runs; nothing returned may alias its constants."""

    @pytest.mark.parametrize("level, fields", [("topic", probe.TOPIC_FIELDS), ("channel", probe.CHANNEL_FIELDS)])
    def test_mutating_results_and_bodies_leaves_later_runs_unchanged(self, level, fields):
        constants = [probe.TOPIC_FIELDS, probe.CHANNEL_FIELDS, probe.TOPIC_SAMPLE_FIELDS, probe.CHANNEL_SAMPLE_FIELDS, probe.COLLAPSE_FIELD]
        snapshot = copy.deepcopy(constants)
        inner = _fake_es()

        def hostile_es(body):
            response = inner(body)
            _scribble(body)  # a consumer that edits the body it was handed
            return response

        candidates = ["tiktok shop", "tiktok"] if level == "topic" else ["cooking", "baking"]
        expected_fields = list(fields)
        first = probe.run_probe(candidates, run_es=hostile_es, fields=fields, level=level)
        assert first["fields"] == expected_fields  # the bodies handed to run_es are copies
        pristine = copy.deepcopy(first)
        _scribble(first)
        second = probe.run_probe(candidates, run_es=hostile_es, fields=fields, level=level)

        assert second == pristine
        assert constants == snapshot

    @pytest.mark.parametrize("mode, query_key", [("phrase", "multi_match"), ("sqs", "simple_query_string")])
    def test_every_body_handed_to_run_es_owns_its_lists(self, mode, query_key):
        es = _fake_es()
        probe.run_probe(["tiktok shop", "tiktok"], run_es=es, fields=probe.TOPIC_FIELDS, mode=mode)
        first, second = es.calls
        assert first["_source"] is not second["_source"]
        assert first["query"]["bool"]["must"][0][query_key]["fields"] is not second["query"]["bool"]["must"][0][query_key]["fields"]
        assert first["query"]["bool"]["must"][0][query_key]["fields"] is not probe.TOPIC_FIELDS


# ----------------------------------------------------------------- select_keywords


def _select_probe(level="topic"):
    if level == "topic":
        return {
            "operator": "OR",
            "level": "topic",
            "keywords": [
                {
                    "keyword": "tiktok shop",
                    "count": 100,
                    "samples": [
                        {"title": "Selling on TikTok Shop", "summary": "guide", "channel_id": 1, "url": "u1"},
                        {"title": "TikTok Shop tips", "summary": "more", "channel_id": 2, "url": "u2"},
                    ],
                },
                {
                    "keyword": "tiktok",
                    "count": 9000,
                    "samples": [
                        {"title": "Dance compilation", "summary": "dances", "channel_id": 3, "url": "u3"},
                        {"title": "Funny TikToks", "summary": "lol", "channel_id": 4, "url": "u4"},
                    ],
                },
            ],
            "dropped": [],
        }
    return {
        "operator": "OR",
        "level": "channel",
        "keywords": [
            {"keyword": "cooking", "count": 50, "samples": [{"name": "Chef Bob", "topic": "recipes", "channel_description": "d", "channel_id": 10}]},
        ],
        "dropped": [],
    }


_FULL_VERDICT = {0: True, 1: True, 2: False, 3: False}


def _verdict_file(tmp_path, name, verdict):
    path = tmp_path / name
    path.write_text(json.dumps([{"i": i, "relevant": rel} for i, rel in verdict.items()]))
    return str(path)


class TestSelectParity:
    @pytest.mark.parametrize("level", ["topic", "channel"])
    def test_emit_batch_equals_command_output(self, level, monkeypatch, capsys):
        probe_json = _select_probe(level)
        lib = _silent(capsys, sk.emit_batch, probe_json)
        status, out, _ = _cli(sk, monkeypatch, capsys, ["--emit-batch"], json.dumps(probe_json))
        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False) + "\n"

    @pytest.mark.parametrize("level, verdict", [("topic", _FULL_VERDICT), ("channel", {0: True})])
    def test_apply_verdict_maps_equals_command_output(self, level, verdict, monkeypatch, capsys, tmp_path):
        probe_json = _select_probe(level)
        lib = _silent(capsys, sk.apply_verdict_maps, probe_json, [verdict])
        status, out, _ = _cli(sk, monkeypatch, capsys, ["--apply", _verdict_file(tmp_path, "v.json", verdict)], json.dumps(probe_json))
        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False, indent=2) + "\n"

    def test_several_passes_are_voted_like_the_command(self, monkeypatch, capsys, tmp_path):
        passes = [_FULL_VERDICT, {0: True, 1: False, 2: False, 3: True}, {0: True, 1: True, 3: True}]
        lib = _silent(capsys, sk.apply_verdict_maps, _select_probe(), passes)
        files = [_verdict_file(tmp_path, f"p{n}.json", p) for n, p in enumerate(passes)]
        status, out, _ = _cli(sk, monkeypatch, capsys, ["--apply", *files], json.dumps(_select_probe()))
        assert status == 0
        assert json.loads(out) == lib


class TestSelectIncompleteVerdicts:
    PARTIAL = {0: True, 1: True}

    def test_missing_lists_exactly_the_unjudged_indices(self):
        with pytest.raises(sk.IncompleteVerdictError) as exc:
            sk.apply_verdict_maps(_select_probe(), [self.PARTIAL])
        assert exc.value.missing == [2, 3]
        assert isinstance(exc.value, sk.SelectInputError) and isinstance(exc.value, ValueError)

    def test_a_sample_judged_by_any_pass_is_not_missing(self):
        with pytest.raises(sk.IncompleteVerdictError) as exc:
            sk.apply_verdict_maps(_select_probe(), [{0: True}, {3: False}])
        assert exc.value.missing == [1, 2]

    def test_missing_is_not_truncated_for_long_gaps(self):
        big = {
            "level": "topic",
            "keywords": [{"keyword": "k", "samples": [{"title": f"t{n}", "summary": "s", "channel_id": n, "url": f"u{n}"} for n in range(25)]}],
        }
        with pytest.raises(sk.IncompleteVerdictError) as exc:
            sk.apply_verdict_maps(big, [])
        assert exc.value.missing == list(range(25))

    def test_command_exits_nonzero_for_the_same_gap(self, monkeypatch, capsys, tmp_path):
        status, out, _ = _cli(sk, monkeypatch, capsys, ["--apply", _verdict_file(tmp_path, "v.json", self.PARTIAL)], json.dumps(_select_probe()))
        assert status != 0
        assert out == ""

    def test_allow_missing_warns_instead_of_raising_and_the_library_stays_silent(self, capsys):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = sk.apply_verdict_maps(_select_probe(), [self.PARTIAL], allow_missing=True)
        assert [w.category for w in caught] == [sk.MissingVerdictWarning]
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", "")
        assert [k["keyword"] for k in out["kept"]] == ["tiktok shop"]

    def test_command_with_allow_missing_prints_the_result_and_the_warning(self, monkeypatch, capsys, tmp_path):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            lib = sk.apply_verdict_maps(_select_probe(), [self.PARTIAL], allow_missing=True)
        status, out, err = _cli(
            sk, monkeypatch, capsys, ["--apply", _verdict_file(tmp_path, "v.json", self.PARTIAL), "--allow-missing"], json.dumps(_select_probe())
        )
        assert status == 0
        assert json.loads(out) == lib
        assert str(caught[0].message) in err


_BAD_PROBES = {
    "not-an-object": [],
    "keywords-not-a-list": {"keywords": "x"},
    "keyword-entry-without-keyword": {"keywords": [{"count": 1}]},
    "samples-not-a-list": {"keywords": [{"keyword": "a", "samples": "oops"}]},
}


class TestSelectBadInput:
    @pytest.mark.parametrize("case", list(_BAD_PROBES))
    def test_library_raises_typed_error_and_command_exits_nonzero(self, case, monkeypatch, capsys, tmp_path):
        bad = _BAD_PROBES[case]
        with pytest.raises(sk.SelectInputError):
            sk.emit_batch(bad)
        with pytest.raises(sk.SelectInputError):
            sk.apply_verdict_maps(bad, [{0: True}])

        for argv in (["--emit-batch"], ["--apply", _verdict_file(tmp_path, "v.json", {0: True})]):
            status, out, _ = _cli(sk, monkeypatch, capsys, argv, json.dumps(bad))
            assert status != 0
            assert out == ""

    def test_verdict_maps_must_be_a_list_of_maps(self):
        with pytest.raises(sk.SelectInputError):
            sk.apply_verdict_maps(_select_probe(), {0: True})

    def test_the_typed_errors_are_value_errors(self):
        assert issubclass(sk.SelectInputError, ValueError)
        assert issubclass(sk.IncompleteVerdictError, sk.SelectInputError)


class TestSelectSharesNothingWithModuleState:
    def test_mutating_results_leaves_later_calls_and_the_input_unchanged(self):
        constants = copy.deepcopy(sk.BATCH_CONTENT_KEYS)
        probe_json = _select_probe()
        original = copy.deepcopy(probe_json)

        batch = sk.emit_batch(probe_json)
        verdicts = sk.apply_verdict_maps(probe_json, [_FULL_VERDICT])
        pristine = copy.deepcopy((batch, verdicts))
        _scribble(batch)
        _scribble(verdicts)

        assert (sk.emit_batch(probe_json), sk.apply_verdict_maps(probe_json, [_FULL_VERDICT])) == pristine
        assert sk.BATCH_CONTENT_KEYS == constants
        assert probe_json == original


# --------------------------------------------------------------- expand_entities

_RESOLVER = {
    "entities": [
        {"name": "Fable 5", "kind": "product"},
        {"name": "Fable Studio", "kind": "company"},
    ],
    "insider_terms": ["day one patch", "rage quit", "speedrun"],
    "aliases": [{"old": "Project Aurora", "new": "Fable 5", "since": "2026-03"}],
    "hashtags": ["#fable5"],
    "collisions": [{"term": "fable", "other_meaning": "short story"}],
    "recency": {"newest": "2026-10"},
    "notes": "launched this year",
    "sources": ["https://example.com/a"],
}


class TestExpandParity:
    def test_expand_equals_command_output(self, monkeypatch, capsys):
        lib = _silent(capsys, ee.expand, _RESOLVER, existing=["fable studio"])
        status, out, _ = _cli(ee, monkeypatch, capsys, ["--existing", "fable studio"], json.dumps(_RESOLVER))
        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False, indent=2) + "\n"

    def test_probe_batch_equals_command_output(self, monkeypatch, capsys):
        lib = _silent(capsys, ee.probe_batch, _RESOLVER, existing=["fable studio"])
        status, out, _ = _cli(ee, monkeypatch, capsys, ["--probe-batch", "--existing", "fable studio"], json.dumps(_RESOLVER))
        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False) + "\n"
        assert lib == ee.expand(_RESOLVER, existing=["fable studio"])["probe_candidates"]

    def test_no_existing_means_an_empty_list(self):
        assert ee.expand(_RESOLVER) == ee.expand(_RESOLVER, existing=[])

    def test_the_insider_cap_still_reaches_the_command(self, monkeypatch, capsys):
        status, out, _ = _cli(ee, monkeypatch, capsys, ["--max-insider", "1"], json.dumps(_RESOLVER))
        assert status == 0
        assert json.loads(out) == ee.expand(_RESOLVER, max_insider=1)
        assert [f["label"] for f in json.loads(out)["families"] if f["kind"] == "insider"] == ["day one patch"]


class TestExpandBadInput:
    @pytest.mark.parametrize("bad", [[1, 2, 3], "text", None])
    def test_library_raises_typed_error_and_command_exits_nonzero(self, bad, monkeypatch, capsys):
        with pytest.raises(ee.ExpandInputError):
            ee.expand(bad)
        with pytest.raises(ee.ExpandInputError):
            ee.probe_batch(bad)
        status, out, _ = _cli(ee, monkeypatch, capsys, [], json.dumps(bad))
        assert status != 0
        assert out == ""

    def test_existing_must_be_a_list_of_strings(self):
        with pytest.raises(ee.ExpandInputError):
            ee.expand(_RESOLVER, existing="fable studio")  # a bare string would be read letter by letter
        with pytest.raises(ee.ExpandInputError):
            ee.expand(_RESOLVER, existing=[3])

    def test_negative_insider_cap_is_refused_on_both_paths(self, monkeypatch, capsys):
        with pytest.raises(ee.ExpandInputError):
            ee.expand(_RESOLVER, max_insider=-1)
        status, _, _ = _cli(ee, monkeypatch, capsys, ["--max-insider", "-1"], json.dumps(_RESOLVER))
        assert status != 0

    def test_the_typed_error_is_a_value_error(self):
        assert issubclass(ee.ExpandInputError, ValueError)


class TestExpandSharesNothingWithModuleState:
    def test_mutating_results_leaves_later_calls_and_the_input_unchanged(self):
        original = copy.deepcopy(_RESOLVER)
        resolver = copy.deepcopy(_RESOLVER)
        constants = (list(ee._ONES), list(ee._TENS), ee.MAX_INSIDER_DEFAULT)

        first = ee.expand(resolver, existing=["x"])
        pristine = copy.deepcopy(first)
        _scribble(first)
        batch = ee.probe_batch(resolver)
        _scribble(batch)

        assert ee.expand(resolver, existing=["x"]) == pristine
        assert resolver == original  # nothing in the output is the caller's own object
        assert constants == (ee._ONES, ee._TENS, ee.MAX_INSIDER_DEFAULT)


# ------------------------------------------------------------------ build_report

_SPEC = {
    "operator": "OR",
    "report_type": "channels",
    "title": "Crypto channels",
    "groups": [
        {"text": "tiktok shop"},
        {"text": "tiktok shop affiliate"},
        {"text": "unboxing", "content_fields": ["title", "summary"]},
        {"text": '("tiktok shop" | dropshipping) -scam'},
        {"text": "refund", "exclude": True},
    ],
}


class TestBuildParity:
    def test_build_equals_command_output(self, monkeypatch, capsys):
        lib = _silent(capsys, br.build, _SPEC)
        status, out, _ = _cli(br, monkeypatch, capsys, [], json.dumps(_SPEC))
        assert status == 0
        assert out == json.dumps(lib, ensure_ascii=False, indent=2) + "\n"
        assert lib["pruned"] and lib["translated"]  # the spec exercises pruning and translation

    def test_app_url_is_honoured_like_the_command_flag(self, monkeypatch, capsys):
        lib = br.build(_SPEC, app_url="https://app.example.test")
        status, out, _ = _cli(br, monkeypatch, capsys, ["--app-url", "https://app.example.test"], json.dumps(_SPEC))
        assert status == 0
        assert json.loads(out) == lib
        assert lib["report_link"].startswith("https://app.example.test/#/")

    @pytest.mark.parametrize("report_type", ["videos", "brands"])
    def test_other_report_types_match_the_command(self, report_type, monkeypatch, capsys):
        spec = {**_SPEC, "report_type": report_type}
        status, out, _ = _cli(br, monkeypatch, capsys, [], json.dumps(spec))
        assert status == 0
        assert json.loads(out) == br.build(spec)


_BAD_SPECS = {
    "bad-operator": {**_SPEC, "operator": "XOR"},
    "bad-report-type": {**_SPEC, "report_type": "podcasts"},
    "no-groups": {"groups": []},
    "unknown-content-field": {"groups": [{"text": "a", "content_fields": ["ai.topic_descriptions"]}]},
    "unsupported-prefix-operator": {"groups": [{"text": "retire*"}]},
    "spec-is-not-an-object": [],
}


class TestBuildBadInput:
    @pytest.mark.parametrize("case", list(_BAD_SPECS))
    def test_library_raises_typed_error_and_command_exits_nonzero(self, case, monkeypatch, capsys):
        with pytest.raises(br.ReportSpecError):
            br.build(_BAD_SPECS[case])
        status, out, _ = _cli(br, monkeypatch, capsys, [], json.dumps(_BAD_SPECS[case]))
        assert status != 0
        assert out == ""

    def test_the_typed_error_is_a_value_error(self):
        assert issubclass(br.ReportSpecError, ValueError)

    def test_sqs_to_app_syntax_still_raises_plain_value_error(self):
        with pytest.raises(ValueError):
            br.sqs_to_app_syntax("retire*")


class TestBuildSharesNothingWithModuleState:
    def test_mutating_results_leaves_later_calls_the_spec_and_constants_unchanged(self):
        constants = [br.DEFAULT_FIELDS, br.VALID_CONTENT_FIELDS, br.REPORT_TYPES]
        snapshot = copy.deepcopy(constants)
        original = copy.deepcopy(_SPEC)
        spec = copy.deepcopy(_SPEC)

        first = br.build(spec)
        pristine = copy.deepcopy(first)
        _scribble(first)

        assert br.build(spec) == pristine
        assert spec == original  # group texts are translated on copies, not on the caller's groups
        assert constants == snapshot

    def test_a_default_content_fields_list_in_the_spec_is_not_handed_back(self):
        spec = {"groups": [{"text": "a"}], "default_content_fields": ["title", "summary"]}
        out = br.build(spec)
        _scribble(out)
        assert spec["default_content_fields"] == ["title", "summary"]


# ------------------------------------------------------------------ import safety

_CLI_LAYER = {
    "probe": {"main", "collect_candidates"},
    "select_keywords": {"main", "load_probe", "load_verdicts", "apply_verdicts"},
    "expand_entities": {"main", "load_resolver"},
    "build_report": {"main"},
}
_PROCESS_IO = {"exit", "stdin", "stdout", "stderr", "argv"}


def _tree(name):
    return ast.parse((_SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", _NAMES)
class TestImportSafe:
    def test_only_the_standard_library_is_imported(self, name):
        modules = set()
        for node in ast.walk(_tree(name)):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, "relative import"
                modules.add(node.module.split(".")[0])
        assert modules <= set(sys.stdlib_module_names)

    def test_import_paths_are_left_alone(self, name):
        for node in ast.walk(_tree(name)):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "sys":
                assert node.attr not in {"path", "modules", "path_hooks", "meta_path"}

    def test_module_level_holds_only_definitions_constants_and_the_command_guard(self, name):
        body = _tree(name).body
        for position, node in enumerate(body):
            if isinstance(node, ast.Expr):
                assert position == 0 and isinstance(node.value, ast.Constant), "only the docstring may be a bare expression"
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                for call in (n for n in ast.walk(node) if isinstance(n, ast.Call)):
                    func = call.func
                    assert isinstance(func, ast.Attribute) and func.attr == "compile" and func.value.id == "re", "only re.compile may run at import"
            elif isinstance(node, ast.If):
                test = node.test
                assert isinstance(test, ast.Compare) and test.left.id == "__name__"
            else:
                assert isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)), ast.dump(node)[:80]

    def test_process_io_stays_in_the_command_layer(self, name):
        offenders = []
        for fn in (n for n in _tree(name).body if isinstance(n, ast.FunctionDef) and n.name not in _CLI_LAYER[name]):
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                    offenders.append((fn.name, "print"))
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr in _PROCESS_IO:
                    offenders.append((fn.name, f"sys.{node.attr}"))
        assert offenders == []

    def test_importing_does_nothing_visible(self, name, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", [name, "--definitely-not-an-option"])
        argv = list(sys.argv)
        _load(name)
        captured = capsys.readouterr()
        assert (captured.out, captured.err) == ("", "")
        assert sys.argv == argv

    def test_it_still_runs_as_a_script(self, name):
        result = subprocess.run([sys.executable, "-I", str(_SCRIPTS / f"{name}.py"), "--help"], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0
