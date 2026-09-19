"""Tests for kw_common — the one shared module for the keyword-research scripts.

Parity tests import the existing scripts by path (the same way
test_kw_scripts_harness.py does) and compare kw_common's output against the
implementation it consolidates, so a port cannot silently change a query.
"""
import hashlib
import importlib.util
import io
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "tl-keyword-research" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kw_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def kc():
    return _load("kw_common")


@pytest.fixture(scope="module")
def probe():
    return _load("probe")


@pytest.fixture(scope="module")
def sc():
    return _load("search_channels")


# The retired fetch_context.py used to be imported here and diffed against
# kw_common live. It is gone, so the values it produced are pinned below:
# captured from that implementation before deletion, they still pin the ported
# behaviour exactly as the parity tests did.
FETCH_CONTEXT_SCOPE_FILTERS = [
    {"term": {"doc_type": "article"}},
    {"term": {"channel.format": 4}},
    {"term": {"channel.id": 466311}},
    {"term": {"content_type": "longform"}},
]
FETCH_CONTEXT_CLEAN_TEXT = ["Bob's shop", "plain text", "", ""]
FETCH_CONTEXT_LITERAL_TERMS = {
    "investing": ["investing"],
    '"tiktok shop" +amazon -dropshipping': ["tiktok shop", "amazon"],
    '("fable 5" | fable5) -keto': ["fable 5", "fable5"],
    'a -("b c" | d) e': ["a", "e"],
    r'"say \"hi\"" x': ['say "hi"', "x"],
}
FETCH_CONTEXT_WINDOWS = [
    "alpha beta shop gamma alpha beta sh…",
    "…op gamma alpha beta shop gamma alpha beta sh…",
    "…op gamma alpha beta shop gamma alpha beta sh…",
]
FETCH_CONTEXT_GROUPS_SHOULD = [
    {"simple_query_string": {"query": '("fable 5" | fable5) -keto',
                             "fields": ["title", "summary"], "default_operator": "and"}},
    {"simple_query_string": {"query": "tiktok shop", "fields": ["title"],
                             "default_operator": "and"}},
]
FETCH_CONTEXT_GROUPS_MUST_NOT = [
    {"simple_query_string": {"query": "dropshipping course",
                             "fields": ["title", "summary"], "default_operator": "and"}},
]


def _fake_run(returncode=0, stdout='{"ok": true}', stderr="", raises=None, script=None):
    """A `subprocess.run` stand-in that records its calls (harness-style)."""
    calls = []
    lock = threading.Lock()

    def run(cmd, input=None, **kw):
        with lock:
            calls.append({"cmd": list(cmd), "input": input, "kw": kw})
            n = len(calls)
        if script is not None:
            return script(n, cmd, kw)
        if raises is not None:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)

    run.calls = calls
    return run


# ------------------------------------------------------------------ run_es

class TestRunEs:
    def test_argv_and_body_on_stdin(self, kc, monkeypatch):
        fake = _fake_run(stdout='{"results": []}')
        monkeypatch.setattr(kc.subprocess, "run", fake)
        assert kc.run_es({"size": 1}) == {"results": []}
        assert fake.calls[0]["cmd"] == ["tl", "db", "es", "-", "--json"]
        assert json.loads(fake.calls[0]["input"]) == {"size": 1}

    def test_highlight_adds_flag(self, kc, monkeypatch):
        fake = _fake_run(stdout="{}")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        kc.run_es({"size": 1}, highlight=True)
        assert fake.calls[0]["cmd"] == ["tl", "db", "es", "-", "--json", "--highlight"]

    def test_default_timeout_is_twenty(self, kc, monkeypatch):
        fake = _fake_run(stdout="{}")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        kc.run_es({})
        assert fake.calls[0]["kw"]["timeout"] == kc.ES_TIMEOUT == 20

    def test_timeout_raises_and_is_never_retried(self, kc, monkeypatch):
        fake = _fake_run(raises=subprocess.TimeoutExpired("tl", 20))
        monkeypatch.setattr(kc.subprocess, "run", fake)
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "timeout"
        assert len(fake.calls) == 1  # a timeout is NOT retried

    def test_transient_failure_retries_once_then_succeeds(self, kc, monkeypatch):
        def script(n, cmd, kw):
            if n == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="",
                                                   stderr="Rate limited. Please wait and try again.")
            return subprocess.CompletedProcess(cmd, 0, stdout='{"total": 3}', stderr="")

        fake = _fake_run(script=script)
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        assert kc.run_es({}) == {"total": 3}
        assert len(fake.calls) == 2

    def test_transient_twice_raises_transient(self, kc, monkeypatch):
        fake = _fake_run(returncode=1, stderr="503 Server error")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "transient"
        assert len(fake.calls) == 2

    def test_non_transient_error_is_not_retried(self, kc, monkeypatch):
        fake = _fake_run(returncode=1, stderr="unknown field 'nope'")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "error"
        assert "unknown field" in str(exc.value)
        assert len(fake.calls) == 1

    def test_retry_false_disables_the_retry(self, kc, monkeypatch):
        fake = _fake_run(returncode=1, stderr="429 Too Many Requests")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        with pytest.raises(kc.EsError):
            kc.run_es({}, retry=False)
        assert len(fake.calls) == 1

    def test_rate_limit_retries_twice_then_succeeds(self, kc, monkeypatch):
        """Sustained contention answers 429 more than once; one retry was not enough."""
        def script(n, cmd, kw):
            if n < 3:
                return subprocess.CompletedProcess(cmd, 3, stdout="",
                                                   stderr="HTTP 429 (non-JSON response from server)")
            return subprocess.CompletedProcess(cmd, 0, stdout='{"total": 7}', stderr="")

        fake = _fake_run(script=script)
        monkeypatch.setattr(kc.subprocess, "run", fake)
        pauses = []
        monkeypatch.setattr(kc.time, "sleep", pauses.append)
        assert kc.run_es({}) == {"total": 7}
        assert len(fake.calls) == 3
        assert pauses == [kc.RETRY_PAUSE, kc.RATE_LIMIT_PAUSE_2]  # 3s then 8s

    def test_rate_limit_three_times_gives_up_with_the_attempt_count(self, kc, monkeypatch):
        fake = _fake_run(returncode=1, stderr="429 Rate limited. Please wait and try again.")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "transient"
        assert "3 attempts" in str(exc.value)
        assert len(fake.calls) == 3

    def test_returncode_3_is_rate_limited_without_any_marker(self, kc, monkeypatch):
        """Exit code 3 is the CLI's rate-limit/server-error code — the body may say nothing."""
        fake = _fake_run(returncode=3, stderr="")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "transient"
        assert len(fake.calls) == 3

    def test_other_transient_markers_keep_the_single_retry(self, kc, monkeypatch):
        fake = _fake_run(returncode=1, stderr="502 Server error")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        with pytest.raises(kc.EsError):
            kc.run_es({})
        assert len(fake.calls) == 2

    def test_bad_json_raises_parse(self, kc, monkeypatch):
        monkeypatch.setattr(kc.subprocess, "run", _fake_run(stdout="not json"))
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({})
        assert exc.value.kind == "parse"


# ---------------------------------------------------------------- deadline

class TestDeadline:
    def test_no_deadline_is_unbounded(self, kc):
        d = kc.Deadline(None)
        assert d.remaining() is None and d.expired is False
        assert d.timeout_for(20) == 20

    def test_timeout_for_caps_at_remaining(self, kc):
        d = kc.Deadline(5)
        assert d.timeout_for(20) <= 5

    def test_expired_deadline_raises_without_calling_subprocess(self, kc, monkeypatch):
        fake = _fake_run()
        monkeypatch.setattr(kc.subprocess, "run", fake)
        d = kc.Deadline(0.0)
        time.sleep(0.01)
        assert d.expired is True
        with pytest.raises(kc.EsError) as exc:
            kc.run_es({}, deadline=d)
        assert exc.value.kind == "deadline"
        assert fake.calls == []  # never shelled out

    def test_from_env(self, kc, monkeypatch):
        monkeypatch.setenv("TL_KW_DEADLINE", "30")
        assert kc.Deadline.from_env().remaining() <= 30
        monkeypatch.setenv("TL_KW_DEADLINE", "nonsense")
        assert kc.Deadline.from_env().remaining() is None
        monkeypatch.delenv("TL_KW_DEADLINE")
        assert kc.Deadline.from_env().remaining() is None


# ----------------------------------------------------------- scope_filters

class TestScopeFilters:
    def test_topic_defaults(self, kc):
        assert kc.scope_filters() == [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.format": 4}},
            {"term": {"content_type": "longform"}},
        ]

    def test_content_type_all_drops_the_filter(self, kc):
        flt = kc.scope_filters(content_type="all")
        assert not any("content_type" in f.get("term", {}) for f in flt)
        assert {"term": {"channel.format": 4}} in flt

    def test_since_and_until(self, kc):
        flt = kc.scope_filters(since="2025-01-01", until="2025-06-30")
        assert {"range": {"publication_date": {"gte": "2025-01-01", "lte": "2025-06-30"}}} in flt

    def test_channel_ids(self, kc):
        flt = kc.scope_filters(channel_ids=[5, 9])
        assert {"terms": {"channel.id": [5, 9]}} in flt

    def test_channel_level_has_no_content_type_or_dates(self, kc):
        flt = kc.scope_filters(level="channel", content_type="longform",
                               since="2025-01-01", channel_ids=[1])
        assert flt == [{"term": {"doc_type": "channel"}}, {"term": {"format": 4}}]

    def test_parity_with_probe_build_body(self, kc, probe):
        body = probe.build_body({"label": "x", "value": "tiktok shop", "mode": "phrase"},
                                fields=["title"], level="topic", samples=3,
                                source_paths=["title"], since="2025-01-01", until="2025-06-30",
                                content_type="short")
        assert body["query"]["bool"]["filter"] == kc.scope_filters(
            level="topic", content_type="short", since="2025-01-01", until="2025-06-30")

    def test_parity_with_probe_build_body_channel_level(self, kc, probe):
        body = probe.build_body({"label": "x", "value": "cooking", "mode": "phrase"},
                                fields=["name"], level="channel", samples=3,
                                source_paths=["name"], since=None, until=None)
        assert body["query"]["bool"]["filter"] == kc.scope_filters(level="channel")

    def test_parity_with_search_channels_filters(self, kc):
        # search_channels.py's own `_filters` helper was retired in favor of this
        # shared one; these are the literal filters it used to produce for the
        # same inputs, pinned directly against kc.scope_filters.
        assert kc.scope_filters(since="2024-02-01", until=None, content_type="longform") == [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.format": 4}},
            {"term": {"content_type": "longform"}},
            {"range": {"publication_date": {"gte": "2024-02-01"}}},
        ]
        assert kc.scope_filters(content_type="all") == [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.format": 4}},
        ]

    def test_parity_with_fetch_context_scope_filters(self, kc):
        mine = kc.scope_filters(content_type="longform", since=None, until=None, channel_ids=[466311])
        theirs = FETCH_CONTEXT_SCOPE_FILTERS
        # fetch_context pinned ONE channel with a `term`; the shared helper takes a
        # list, so compare the non-channel clauses plus the equivalent id clause.
        assert [f for f in theirs if "channel.id" not in f.get("term", {})] == \
               [f for f in mine if "channel.id" not in f.get("terms", {})]
        assert {"terms": {"channel.id": [466311]}} in mine


# --------------------------------------------------------------- highlight

class TestHighlight:
    def test_clause_shape(self, kc):
        cl = kc.highlight_clause(["title", "transcript"], fragment_size=120, fragments=3)
        assert cl["fields"] == {"title": {"fragment_size": 120, "number_of_fragments": 3},
                                "transcript": {"fragment_size": 120, "number_of_fragments": 3}}
        assert cl["pre_tags"] == ["<<"] and cl["post_tags"] == [">>"]
        # scope filters must not highlight (a `channel.format: 4` scope marked
        # "PlayStation <<4>>" while it was off)
        assert cl["require_field_match"] is True
        assert "highlight_query" not in cl

    def test_clause_passes_the_highlight_query_through(self, kc):
        q = {"bool": {"should": [{"simple_query_string": {"query": "cannes +lions"}}]}}
        cl = kc.highlight_clause(["title"], highlight_query=q)
        assert cl["highlight_query"] == q

    def test_fragments_of_cli_row_orders_fields_and_keeps_markers(self, kc):
        row = {"id": 1, "title": "t", "highlight": {"transcript": ["a <<shop>> b"],
                                                    "title": ["my <<shop>>"]}}
        assert kc.fragments_of(row) == [
            {"field": "title", "text": "my <<shop>>", "hits": 1},
            {"field": "transcript", "text": "a <<shop>> b", "hits": 1},
        ]

    def test_fragments_of_counts_the_hits_per_fragment(self, kc):
        row = {"highlight": {"summary": ["one <<lions>> here"],
                             "transcript": ["<<cannes>> <<lions>> <<advertising>>"],
                             "title": ["nothing marked"]}}
        assert {f["field"]: f["hits"] for f in kc.fragments_of(row)} == {
            "title": 0, "summary": 1, "transcript": 3}

    def test_fragments_of_raw_es_hit_and_entity_unescaping(self, kc):
        hit = {"_source": {"title": "x"},
               "highlight": {"summary": ["Bob&amp;#39;s   <<shop>>\n   deal"]}}
        assert kc.fragments_of(hit) == [{"field": "summary", "text": "Bob's <<shop>> deal",
                                         "hits": 1}]

    def test_fragments_of_without_highlight_is_empty(self, kc):
        assert kc.fragments_of({"id": 1, "title": "t"}) == []

    def test_fragments_of_unknown_field_comes_last(self, kc):
        row = {"highlight": {"hashtags": ["<<a>>"], "title": ["<<b>>"]}}
        assert [f["field"] for f in kc.fragments_of(row)] == ["title", "hashtags"]


# --------------------------------------------------------------- accessors

class TestAccessors:
    def test_hits_of_prefers_results(self, kc):
        assert kc.hits_of({"results": [{"id": 1}], "hits": {"hits": [{"id": 2}]}}) == [{"id": 1}]

    def test_hits_of_falls_back_to_raw_es(self, kc):
        assert kc.hits_of({"hits": {"hits": [{"_id": "a"}]}}) == [{"_id": "a"}]
        assert kc.hits_of({}) == []

    def test_source_of_handles_both_shapes(self, kc):
        assert kc.source_of({"_source": {"title": "a"}}) == {"title": "a"}
        assert kc.source_of({"title": "a"}) == {"title": "a"}

    def test_get_path_nested_and_flat(self, kc):
        assert kc.get_path({"channel": {"id": 5}}, "channel.id") == 5
        assert kc.get_path({"channel.id": 5}, "channel.id") == 5
        assert kc.get_path({"channel": {"name": "n"}}, "channel.id") is None

    def test_extract_total_parity_with_probe(self, kc, probe):
        for data in ({"total": 12}, {"hits": {"total": {"value": 7}}}, {"hits": {"total": 4}}, {}):
            assert kc.extract_total(data) == probe.extract_total(data)

    def test_agg_root(self, kc):
        assert kc.agg_root({"aggregations": {"a": 1}}) == {"a": 1}
        assert kc.agg_root({"aggs": {"b": 2}}) == {"b": 2}
        assert kc.agg_root({}) == {}


# -------------------------------------------------------------------- text

class TestText:
    def test_clean_text_parity_with_fetch_context(self, kc):
        raws = ('<text start="1">Bob&amp;#39;s   shop</text>', "plain   text", None, 7)
        assert [kc.clean_text(raw) for raw in raws] == FETCH_CONTEXT_CLEAN_TEXT

    @pytest.mark.parametrize("expr", list(FETCH_CONTEXT_LITERAL_TERMS))
    def test_literal_terms_parity_with_fetch_context(self, kc, expr):
        assert kc.literal_terms(expr) == FETCH_CONTEXT_LITERAL_TERMS[expr]

    def test_windows_parity_with_fetch_context(self, kc):
        text = ("alpha beta shop gamma " * 20).strip()
        assert kc.windows(text, ["shop"], window=20, max_snippets=3) == FETCH_CONTEXT_WINDOWS

    def test_windows_shares_budget_across_terms(self, kc):
        text = "one shop two mall three shop four mall five"
        out = kc.windows(text, ["shop", "mall"], window=5, max_snippets=2)
        assert len(out) == 2

    def test_windows_empty_inputs(self, kc):
        assert kc.windows("", ["x"]) == [] and kc.windows("abc", []) == []

    @pytest.mark.parametrize("text,expected", [
        # an unstructured multi-word group is quoted as one phrase
        ("tiktok shop", '"tiktok shop"'),
        # a single word has nothing to quote
        ("one", "one"),
        # already-structured boolean text (|, (), ") is left verbatim
        ('("a b" | c)', '("a b" | c)'),
        ("a -b", "a -b"),
        ("a - b", "a - b"),
    ])
    def test_phrase_if_plain_parity(self, kc, text, expected):
        # search_channels.py's own copy of this helper was retired in favor of
        # this shared one; these are the values it used to agree on.
        assert kc.phrase_if_plain(text) == expected

    def test_valid_date(self, kc):
        assert kc.valid_date("2025-01-01") == "2025-01-01"
        assert not kc.valid_date("2025-13-99")
        assert not kc.valid_date("nope")
        assert not kc.valid_date(None)

    def test_months_ago_iso_parity(self, kc, probe):
        assert kc.months_ago_iso(6) == probe.months_ago_iso(6)
        assert kc.months_ago_iso(18) == probe.months_ago_iso(18)


# ------------------------------------------------------------------ groups

GROUPS_SPEC = {
    "operator": "OR",
    "default_content_fields": ["title", "summary"],
    "groups": [
        {"text": '("fable 5" | fable5) -keto'},
        {"text": "tiktok shop", "content_fields": ["title"]},
        {"text": "dropshipping course", "exclude": True},
    ],
}


@pytest.fixture
def groups_path(tmp_path):
    p = tmp_path / "groups.json"
    p.write_text(json.dumps(GROUPS_SPEC), encoding="utf-8")
    return str(p)


class TestGroups:
    def test_load_groups_file_shape(self, kc, groups_path):
        spec = kc.load_groups_file(groups_path)
        assert spec["operator"] == "OR"
        assert spec["default_content_fields"] == ["title", "summary"]
        assert [g["text"] for g in spec["groups"]] == \
            ['("fable 5" | fable5) -keto', "tiktok shop", "dropshipping course"]
        assert spec["groups"][0]["content_fields"] is None
        assert spec["groups"][1]["content_fields"] == ["title"]
        assert spec["groups"][2]["exclude"] is True

    def test_load_groups_file_accepts_a_bare_list(self, kc, tmp_path):
        p = tmp_path / "g.json"
        p.write_text(json.dumps(["alpha", {"text": "beta", "exclude": True}]), encoding="utf-8")
        spec = kc.load_groups_file(str(p))
        assert [(g["text"], g["exclude"]) for g in spec["groups"]] == \
            [("alpha", False), ("beta", True)]
        assert spec["operator"] is None and spec["default_content_fields"] is None

    def test_load_groups_file_rejects_channel_level_fields(self, kc, tmp_path):
        p = tmp_path / "g.json"
        p.write_text(json.dumps({"groups": [{"text": "a", "content_fields": ["channel_description"]}]}),
                     encoding="utf-8")
        with pytest.raises(kc.BatchError) as exc:
            kc.load_groups_file(str(p))
        assert "lives on channel docs" in str(exc.value)

    def test_load_groups_file_rejects_unknown_fields(self, kc, tmp_path):
        p = tmp_path / "g.json"
        p.write_text(json.dumps({"groups": [{"text": "a", "content_fields": ["nope"]}]}),
                     encoding="utf-8")
        with pytest.raises(kc.BatchError) as exc:
            kc.load_groups_file(str(p))
        assert "unknown content field" in str(exc.value)

    def test_es_field_keeps_boosts(self, kc):
        assert kc.es_field("title^4") == "title^4"
        assert kc.es_field("summary") == "summary"

    def test_groups_query_parity_with_search_channels(self, kc, sc, groups_path):
        spec = kc.load_groups_file(groups_path)
        mine = kc.groups_query(spec)
        mine["filter"] = kc.scope_filters(content_type="longform")
        theirs = sc.groups_bool(
            [g["text"] for g in spec["groups"] if not g["exclude"]],
            not_terms=[], fields=spec["default_content_fields"],
            since=None, until=None, operator="OR", content_type="longform",
            group_fields={1: ["title"]},
            not_groups=[{"text": "dropshipping course"}],
        )
        assert mine == theirs

    def test_groups_query_parity_with_fetch_context(self, kc, groups_path):
        spec = kc.load_groups_file(groups_path)
        mine = kc.groups_query(spec)
        mine["filter"] = kc.scope_filters(content_type="longform", channel_ids=[7])
        assert mine["should"] == FETCH_CONTEXT_GROUPS_SHOULD
        assert mine["minimum_should_match"] == 1
        assert mine["must_not"] == FETCH_CONTEXT_GROUPS_MUST_NOT

    def test_groups_query_and_operator(self, kc, groups_path):
        q = kc.groups_query(kc.load_groups_file(groups_path), operator="AND")
        assert "must" in q and "should" not in q
        assert len(q["must"]) == 2 and len(q["must_not"]) == 1

    def test_groups_query_operator_defaults_to_or(self, kc):
        q = kc.groups_query({"groups": [{"text": "a"}]})
        assert q["should"][0]["simple_query_string"]["fields"] == kc.TOPIC_FIELDS
        assert q["minimum_should_match"] == 1


class TestRequiredTerms:
    """kw_common.required_terms — the anchors every match of an sqs expression
    carries, which is what a snippet has to show to be evidence."""

    @pytest.mark.parametrize("expression,expected", [
        # the live case: only the anchor is required, the OR group is not
        ("croisette +(advertising|marketing|agency|brand)", ["croisette"]),
        # default_operator is AND, so bare top-level words are all required
        ("cannes lions", ["cannes", "lions"]),
        # `+` required, `-` negated phrase excluded
        ('cannes +lions -"film festival"', ["cannes", "lions"]),
        # a quoted phrase is one term; everything in the negated group is out
        ('+"tiktok shop" -(keto | diet)', ["tiktok shop"]),
        # a parenthesised group with no `|` still contributes its terms
        ("a -b +(c d)", ["a", "c", "d"]),
    ])
    def test_expressions(self, kc, expression, expected):
        assert kc.required_terms(expression) == expected

    def test_duplicates_collapse_and_empty_is_empty(self, kc):
        assert kc.required_terms("cannes cannes lions") == ["cannes", "lions"]
        assert kc.required_terms("") == []


# ------------------------------------------------------------------- cache

class TestCache:
    def test_round_trip(self, kc, tmp_path, monkeypatch):
        monkeypatch.setattr(kc, "cache_namespace", lambda: "ns123")
        body, data = {"size": 2, "q": "x"}, {"total": 9}
        assert kc.cache_load(str(tmp_path), body, 24) is None
        kc.cache_store(str(tmp_path), body, data)
        assert kc.cache_load(str(tmp_path), body, 24) == data

    def test_highlight_has_its_own_key(self, kc, tmp_path, monkeypatch):
        monkeypatch.setattr(kc, "cache_namespace", lambda: "ns123")
        body = {"size": 1}
        kc.cache_store(str(tmp_path), body, {"plain": True})
        assert kc.cache_key(body) != kc.cache_key(body, highlight=True)
        assert kc.cache_load(str(tmp_path), body, 24, highlight=True) is None

    def test_expired_entry_is_ignored(self, kc, tmp_path, monkeypatch):
        monkeypatch.setattr(kc, "cache_namespace", lambda: "ns123")
        body = {"size": 3}
        kc.cache_store(str(tmp_path), body, {"total": 1})
        path = tmp_path / "ns123" / (kc.cache_key(body) + ".json")
        os.utime(path, (time.time() - 7200, time.time() - 7200))
        assert kc.cache_load(str(tmp_path), body, 1) is None
        assert kc.cache_load(str(tmp_path), body, 24) == {"total": 1}

    def test_no_namespace_disables_the_cache(self, kc, tmp_path, monkeypatch):
        monkeypatch.setattr(kc, "cache_namespace", lambda: None)
        kc.cache_store(str(tmp_path), {"a": 1}, {"total": 1})
        assert kc.cache_load(str(tmp_path), {"a": 1}, 24) is None
        assert list(tmp_path.iterdir()) == []

    def test_namespace_runs_tl_whoami_once_under_a_lock(self, kc, monkeypatch):
        fake = _fake_run(stdout=json.dumps({"user": {"id": 42}}))
        monkeypatch.setattr(kc.subprocess, "run", fake)
        kc._reset_cache_namespace()
        try:
            out = [None] * 8
            threads = [threading.Thread(target=lambda i=i: out.__setitem__(i, kc.cache_namespace()))
                       for i in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(set(out)) == 1 and out[0]
            assert len(fake.calls) == 1
            assert fake.calls[0]["cmd"] == ["tl", "whoami", "--json"]
        finally:
            kc._reset_cache_namespace()

    def test_namespace_retries_tl_whoami_once_then_succeeds(self, kc, monkeypatch):
        def script(n, cmd, kw):
            if n == 1:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Rate limited")
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"user": {"id": 42}}),
                                               stderr="")

        fake = _fake_run(script=script)
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        kc._reset_cache_namespace()
        try:
            ns = kc.cache_namespace()
            assert len(fake.calls) == 2 and ns and not ns.startswith("shared-")
        finally:
            kc._reset_cache_namespace()

    def test_namespace_falls_back_to_a_shared_one_and_warns_once(self, kc, monkeypatch, capsys):
        """A rate-limited `tl whoami` used to disable the cache for a whole run."""
        fake = _fake_run(returncode=1, stderr="429 Rate limited")
        monkeypatch.setattr(kc.subprocess, "run", fake)
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        monkeypatch.setenv("TL_API_URL", "https://example.test")
        kc._reset_cache_namespace()
        try:
            ns = kc.cache_namespace()
            assert ns == kc.cache_namespace()          # memoized, no second warning
            assert ns.startswith("shared-") and len(ns) == len("shared-") + 12
            assert ns[len("shared-"):] == hashlib.sha1(b"https://example.test").hexdigest()[:12]
            assert len(fake.calls) == 2                # the two whoami attempts only
            errs = [ln for ln in capsys.readouterr().err.splitlines() if ln.strip()]
            assert errs == ["probe cache: tl whoami unavailable, using the shared namespace"]
        finally:
            kc._reset_cache_namespace()

    def test_shared_namespace_is_per_endpoint(self, kc, monkeypatch):
        monkeypatch.setattr(kc.subprocess, "run", _fake_run(returncode=1, stderr="429"))
        monkeypatch.setattr(kc.time, "sleep", lambda *_: None)
        seen = []
        try:
            for url in ("https://a.test", "https://b.test"):
                monkeypatch.setenv("TL_API_URL", url)
                kc._reset_cache_namespace()
                seen.append(kc.cache_namespace())
            monkeypatch.delenv("TL_API_URL")
            kc._reset_cache_namespace()
            seen.append(kc.cache_namespace())
        finally:
            kc._reset_cache_namespace()
        assert len(set(seen)) == 3

    def test_run_es_cached_hits_then_misses(self, kc, tmp_path, monkeypatch):
        monkeypatch.setattr(kc, "cache_namespace", lambda: "ns123")
        fake = _fake_run(stdout='{"total": 5}')
        monkeypatch.setattr(kc.subprocess, "run", fake)
        data, hit = kc.run_es_cached({"size": 1}, cache_dir=str(tmp_path), ttl_hours=24)
        assert (data, hit) == ({"total": 5}, False)
        data, hit = kc.run_es_cached({"size": 1}, cache_dir=str(tmp_path), ttl_hours=24)
        assert (data, hit) == ({"total": 5}, True)
        assert len(fake.calls) == 1
        kc.run_es_cached({"size": 1}, cache_dir=str(tmp_path), ttl_hours=24, no_cache=True)
        assert len(fake.calls) == 2


# ---------------------------------------------------------------- parallel

class TestParallelMap:
    def test_results_keep_input_order(self, kc):
        def fn(i):
            time.sleep((10 - i) / 1000)
            return i * 2

        assert kc.parallel_map(fn, range(10), workers=5) == [i * 2 for i in range(10)]

    def test_exceptions_are_captured_per_item(self, kc):
        def fn(i):
            if i == 1:
                raise ValueError("boom")
            return i

        out = kc.parallel_map(fn, [0, 1, 2], workers=3)
        assert out[0] == 0 and out[2] == 2
        assert isinstance(out[1], ValueError) and str(out[1]) == "boom"

    def test_serial_path_also_captures(self, kc):
        def fn(i):
            raise RuntimeError("x")

        assert isinstance(kc.parallel_map(fn, [1], workers=1)[0], RuntimeError)

    def test_empty_items(self, kc):
        assert kc.parallel_map(lambda x: x, []) == []


# ----------------------------------------------------------------- run I/O

class TestRunIO:
    def test_record_event_file_layout(self, kc, tmp_path):
        path = kc.record_event(str(tmp_path), "probe", ["--level", "topic"],
                               time.monotonic() - 1.5, {"kept": 3})
        assert path and os.path.dirname(path) == str(tmp_path / "events")
        name = os.path.basename(path)
        assert name.endswith(f"-probe-{os.getpid()}.json") and name[8] == "T"
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        assert rec["script"] == "probe" and rec["argv"] == ["--level", "topic"]
        assert rec["output"] == {"kept": 3} and rec["elapsed_seconds"] >= 1.0
        assert rec["started"].endswith("+00:00")

    def test_record_event_without_run_dir_is_a_noop(self, kc):
        assert kc.record_event(None, "probe", [], time.monotonic(), {}) is None

    def test_record_event_never_raises(self, kc, tmp_path):
        blocker = tmp_path / "events"
        blocker.write_text("not a dir", encoding="utf-8")
        assert kc.record_event(str(tmp_path), "probe", [], time.monotonic(), {}) is None

    def test_write_and_read_json(self, kc, tmp_path):
        p = str(tmp_path / "x.json")
        kc.write_json_atomic(p, {"a": [1, 2]})
        assert kc.read_json(p, "thing") == {"a": [1, 2]}
        assert not list(tmp_path.glob("*.tmp"))

    def test_read_json_raises_batch_error(self, kc, tmp_path):
        with pytest.raises(kc.BatchError) as exc:
            kc.read_json(str(tmp_path / "missing.json"), "manifest")
        assert "could not read manifest" in str(exc.value)

    def test_emit_prints_json_and_records(self, kc, tmp_path, capsys):
        kc.emit({"ok": 1}, run_dir=str(tmp_path), script="probe", argv=["-x"],
                started=time.monotonic())
        assert json.loads(capsys.readouterr().out) == {"ok": 1}
        assert len(list((tmp_path / "events").iterdir())) == 1


# ------------------------------------------------------------- stdin guard

class _SocketStdin(io.TextIOWrapper):
    """A stdin that looks like the harness's: a unix socket that never closes."""

    def __init__(self):
        a, self._b = socket.socketpair()
        super().__init__(a.makefile("rb"), encoding="utf-8")
        self._fd = a.fileno()

    def fileno(self):
        return self._fd


class TestStdinGuard:
    def test_socket_stdin_is_not_readable(self, kc, monkeypatch):
        sock = _SocketStdin()
        monkeypatch.setattr(kc.sys, "stdin", sock)
        assert kc.stdin_is_readable() is False

    def test_regular_file_stdin_is_readable(self, kc, monkeypatch, tmp_path):
        p = tmp_path / "in.json"
        p.write_text("[]", encoding="utf-8")
        with open(p, encoding="utf-8") as fh:
            monkeypatch.setattr(kc.sys, "stdin", fh)
            assert kc.stdin_is_readable() is True

    def test_broken_stdin_is_not_readable(self, kc, monkeypatch):
        monkeypatch.setattr(kc.sys, "stdin", object())
        assert kc.stdin_is_readable() is False


class TestDeadlineFloor:
    """A call that cannot get MIN_CALL_SECONDS is refused as a deadline: a
    sub-second ES call lands in `failed: timeout` and reads as a broken query."""

    def test_under_the_floor_is_a_deadline(self, kc):
        with pytest.raises(kc.EsError) as exc:
            kc.Deadline(1.5).timeout_for(20)
        assert exc.value.kind == "deadline"

    def test_above_the_floor_still_caps_at_remaining(self, kc):
        assert 0 < kc.Deadline(5).timeout_for(20) <= 5


class TestEventTiming:
    def test_record_event_lifts_the_shared_timing_numbers(self, kc, tmp_path):
        path = kc.record_event(str(tmp_path), "probe", [], time.monotonic(),
                               {"keywords": [], "timing": {"elapsed_seconds": 12.3,
                                                           "es_calls": 7, "cache_hits": 2}})
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        assert rec["elapsed_seconds"] == 12.3
        assert rec["es_calls"] == 7 and rec["cache_hits"] == 2
        assert rec["output"]["timing"]["es_calls"] == 7      # still where it came from

    def test_an_output_without_timing_keeps_the_process_elapsed(self, kc, tmp_path):
        path = kc.record_event(str(tmp_path), "probe", [], time.monotonic() - 1.0, {"kept": 1})
        rec = json.loads(Path(path).read_text(encoding="utf-8"))
        assert rec["elapsed_seconds"] >= 1.0 and "es_calls" not in rec
