"""Harness-safety tests for the tl-keyword-research scripts.

Under agent harnesses (Claude Code's Bash tool) stdin is an open unix socket:
not a TTY, never at EOF. Any script that falls through to `sys.stdin.read()`
blocks forever before its first ES call. These tests pin the guard, the
`--groups-file` input path that replaces shell-quoting large filters, the
parallel/cached probe loop, and the parallel context fetch.
"""
import concurrent.futures
import importlib.util
import io
import json
import os
import socket
import stat
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


@pytest.fixture
def sc():
    return _load("search_channels")


@pytest.fixture
def sv():
    return _load("search_videos")


@pytest.fixture
def probe():
    return _load("probe")


@pytest.fixture
def ctx():
    return _load("fetch_context")


class _SocketStdin(io.TextIOWrapper):
    """A stdin that looks like the harness's: a unix socket that never closes."""

    def __init__(self):
        a, self._b = socket.socketpair()
        super().__init__(a.makefile("rb"), encoding="utf-8")
        self._fd = a.fileno()

    def fileno(self):
        return self._fd


def _fake_es(counts_by_query=None, delay=0.0, fail_first=None):
    """subprocess.run stand-in for `tl db es`; records bodies, optional delay/failure."""
    calls = []
    lock = threading.Lock()
    state = {"failed": set()}

    def run(cmd, input=None, **kw):
        body = json.loads(input)
        with lock:
            calls.append(body)
        if delay:
            time.sleep(delay)
        key = json.dumps(body, sort_keys=True)
        if fail_first is not None and key not in state["failed"] and fail_first(body):
            with lock:
                state["failed"].add(key)
            # the CLI's real wording (tl_cli/client/errors.py) — no status code in it
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Rate limited. Please wait and try again.")
        total = (counts_by_query or {}).get(_probe_term(body), 7)
        env = {"results": [], "total": total,
               "aggregations": {"distinct_channels": {"value": max(1, total // 2)},
                                "by_channel": {"buckets": []}}}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(env), stderr="")

    run.calls = calls
    return run


def _probe_term(body):
    """Pull the probed keyword out of a probe body (phrase or sqs)."""
    q = json.dumps(body.get("query", {}))
    for marker in ('"query": "',):
        i = q.find(marker)
        if i >= 0:
            j = q.find('"', i + len(marker))
            return q[i + len(marker):j]
    return None


# ---------------------------------------------------------------- stdin guard

class TestStdinGuard:
    @pytest.mark.parametrize("name", ["search_channels", "search_videos", "probe"])
    def test_socket_stdin_is_never_read(self, monkeypatch, name):
        mod = _load(name)
        sock = _SocketStdin()
        monkeypatch.setattr(mod.sys, "stdin", sock)
        assert mod.stdin_is_readable() is False
        collect = getattr(mod, "collect_keywords", None) or mod.collect_candidates
        assert collect([]) == []  # returns instantly instead of blocking

    def test_pipe_and_file_stdin_are_read(self, monkeypatch, tmp_path, sc):
        f = tmp_path / "kw.json"
        f.write_text('["a", "b"]')
        with open(f, encoding="utf-8") as fh:
            monkeypatch.setattr(sc.sys, "stdin", fh)
            assert sc.stdin_is_readable() is True
            assert sc.collect_keywords([]) == ["a", "b"]
        r, w = os.pipe()
        os.write(w, b'["c"]')
        os.close(w)
        with os.fdopen(r, encoding="utf-8") as fh:
            monkeypatch.setattr(sc.sys, "stdin", fh)
            assert sc.stdin_is_readable() is True
            assert sc.collect_keywords([]) == ["c"]

    def test_group_run_with_socket_stdin_reaches_es(self, monkeypatch, capsys, sc):
        """The exact shape that hung: --group only, no positional keywords."""
        monkeypatch.setattr(sc.sys, "stdin", _SocketStdin())
        fake = _fake_es()
        monkeypatch.setattr(sc.subprocess, "run", fake)
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "--no-share",
                                             "--no-enrich", "--group", '"youtube policy"'])
        sc.main()
        assert len(fake.calls) == 1
        out = json.loads(capsys.readouterr().out)
        assert out["query"]["groups"] == ['"youtube policy"']


# ---------------------------------------------------------------- groups-file

class TestGroupsFile:
    @pytest.mark.parametrize("payload", [
        {"groups": [{"text": "a +b"}, {"text": '"c d"'}]},
        [{"text": "a +b"}, {"text": '"c d"'}],
        ["a +b", '"c d"'],
    ])
    def test_three_shapes(self, tmp_path, sc, payload):
        f = tmp_path / "groups.json"
        f.write_text(json.dumps(payload))
        groups, default, op = sc.load_groups_file(str(f))
        assert [g["text"] for g in groups] == ["a +b", '"c d"'] and default is None and op is None
        assert all(g["content_fields"] is None and g["exclude"] is False for g in groups)

    def test_report_semantics_preserved(self, monkeypatch, capsys, tmp_path, sc):
        """Per-group content_fields, default_content_fields and exclude groups
        must shape the ES query exactly as build_report.py would the link."""
        f = tmp_path / "groups.json"
        f.write_text(json.dumps({"default_content_fields": ["title", "summary"],
                                 "groups": [{"text": "retirement +planning", "content_fields": ["title"]},
                                            {"text": "pension"},
                                            {"text": "scam", "exclude": True}]}))
        monkeypatch.setattr(sc.sys, "stdin", _SocketStdin())
        fake = _fake_es()
        monkeypatch.setattr(sc.subprocess, "run", fake)
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "--no-share",
                                             "--no-enrich", "--groups-file", str(f)])
        sc.main()
        body = fake.calls[0]["query"]["bool"]
        clauses = [c["simple_query_string"] for c in body["should"]]
        assert [c["query"] for c in clauses] == ["retirement +planning", "pension"]
        assert clauses[0]["fields"] == ["title^4"]            # boost carried from the default field list
        assert clauses[1]["fields"] == ["title^4", "summary^2"]
        # the excluded group inherits default_content_fields, exactly as the report would
        assert body["must_not"] == [{"simple_query_string": {"query": "scam", "fields": ["title^4", "summary^2"],
                                                             "default_operator": "and"}}]
        out = json.loads(capsys.readouterr().out)
        assert out["query"]["not_groups"] == ["scam"]
        assert out["expression"]["expression"].endswith(" AND NOT (scam)")

    def test_file_operator_applies_unless_overridden(self, monkeypatch, capsys, tmp_path, sc):
        f = tmp_path / "groups.json"
        f.write_text(json.dumps({"operator": "AND", "groups": [{"text": "a"}, {"text": "b"}]}))
        monkeypatch.setattr(sc.sys, "stdin", _SocketStdin())
        fake = _fake_es()
        monkeypatch.setattr(sc.subprocess, "run", fake)
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "--no-share",
                                             "--no-enrich", "--groups-file", str(f)])
        sc.main()
        assert "must" in fake.calls[0]["query"]["bool"]  # AND from the file
        assert json.loads(capsys.readouterr().out)["query"]["operator"] == "AND"
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "--no-share",
                                             "--no-enrich", "--operator", "OR", "--groups-file", str(f)])
        sc.main()
        assert "should" in fake.calls[1]["query"]["bool"]  # explicit flag wins

    def test_excluded_group_keeps_its_field_scope_and_positional_offsets(self, monkeypatch, capsys, tmp_path, sc):
        f = tmp_path / "groups.json"
        f.write_text(json.dumps({"groups": [{"text": "pension", "content_fields": ["title"]},
                                            {"text": "scam", "exclude": True, "content_fields": ["title"]}]}))
        monkeypatch.setattr(sc.sys, "stdin", _SocketStdin())
        fake = _fake_es()
        monkeypatch.setattr(sc.subprocess, "run", fake)
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--intensity", "--no-share",
                                             "--no-enrich", "--groups-file", str(f), "seed one", "seed2"])
        sc.main()
        body = fake.calls[0]["query"]["bool"]
        should = [c["simple_query_string"] for c in body["should"]]
        assert [c["query"] for c in should] == ['"seed one"', "seed2", "pension"]
        assert should[0]["fields"] == sc.DEFAULT_FIELDS.split(",")  # positional seeds keep the defaults
        assert should[2]["fields"] == ["title^4"]                     # the file group's override moved with it
        assert body["must_not"][0]["simple_query_string"]["fields"] == ["title^4"]

    @pytest.mark.parametrize("field", ["channel_description", "channel_topic_description", "nonsense"])
    def test_unsearchable_report_fields_fail_loudly(self, tmp_path, sc, sv, field):
        for mod in (sc, sv):
            with pytest.raises(SystemExit) as exc:
                mod.boosted([field], mod.DEFAULT_FIELDS.split(","))
            assert field in str(exc.value)
        assert sc.boosted(["hashtags", "title"], ["title^4"]) == ["hashtags", "title^4"]

    def test_only_excludes_is_an_error(self, tmp_path, sc, monkeypatch):
        f = tmp_path / "groups.json"
        f.write_text(json.dumps([{"text": "scam", "exclude": True}]))
        monkeypatch.setattr(sc.sys, "stdin", _SocketStdin())
        monkeypatch.setattr(sc.sys, "argv", ["search_channels.py", "--groups-file", str(f)])
        with pytest.raises(SystemExit):
            sc.main()

    def test_appends_to_group_flags(self, monkeypatch, capsys, tmp_path, sv):
        f = tmp_path / "groups.json"
        f.write_text(json.dumps({"groups": [{"text": "x | y"}]}))
        monkeypatch.setattr(sv.sys, "stdin", _SocketStdin())
        fake = _fake_es()
        monkeypatch.setattr(sv.subprocess, "run", fake)
        monkeypatch.setattr(sv.sys, "argv", ["search_videos.py", "--no-enrich", "--group", "a +b",
                                             "--groups-file", str(f)])
        sv.main()
        out = json.loads(capsys.readouterr().out)
        assert out["query"]["groups"] == ["a +b", "x | y"]

    def test_bad_file_fails_loudly(self, tmp_path, sc):
        f = tmp_path / "groups.json"
        f.write_text("{not json")
        with pytest.raises(SystemExit):
            sc.load_groups_file(str(f))


# ---------------------------------------------------------------- probe loop

class TestProbeParallelAndCache:
    def _run(self, probe, monkeypatch, capsys, argv, fake, cache_dir, ns="test-identity"):
        monkeypatch.setattr(probe.subprocess, "run", fake)
        monkeypatch.setattr(probe, "_CACHE_NS", ns)
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--samples", "0", "--no-recency",
                                                "--cache-dir", str(cache_dir)] + argv)
        probe.main()
        return json.loads(capsys.readouterr().out)

    def test_parallel_preserves_ranking_and_counts(self, monkeypatch, capsys, tmp_path, probe):
        counts = {"alpha": 50, "beta": 5, "gamma": 500}
        fake = _fake_es(counts, delay=0.05)
        out = self._run(probe, monkeypatch, capsys, ["--workers", "3", "alpha", "beta", "gamma"], fake, tmp_path)
        assert [k["keyword"] for k in out["keywords"]] == ["gamma", "alpha", "beta"]
        assert out["timing"]["es_calls"] == 3 and out["timing"]["cache_hits"] == 0
        assert out["timing"]["workers"] == 3

    def test_second_run_is_served_from_cache(self, monkeypatch, capsys, tmp_path, probe):
        fake = _fake_es({"alpha": 50})
        self._run(probe, monkeypatch, capsys, ["alpha"], fake, tmp_path)
        assert len(fake.calls) == 1
        out = self._run(probe, monkeypatch, capsys, ["alpha"], fake, tmp_path)
        assert len(fake.calls) == 1  # no second ES call
        assert out["timing"] == {"elapsed_seconds": out["timing"]["elapsed_seconds"],
                                 "es_calls": 0, "cache_hits": 1, "workers": probe.PROBE_WORKERS}
        assert out["keywords"][0]["count"] == 50

    def test_cache_key_includes_fields_and_scope(self, monkeypatch, capsys, tmp_path, probe):
        fake = _fake_es({"alpha": 50})
        self._run(probe, monkeypatch, capsys, ["--fields", "title", "alpha"], fake, tmp_path)
        self._run(probe, monkeypatch, capsys, ["--fields", "title,summary", "alpha"], fake, tmp_path)
        self._run(probe, monkeypatch, capsys, ["--fields", "title", "--content-type", "all", "alpha"], fake, tmp_path)
        assert len(fake.calls) == 3

    def test_cache_is_namespaced_by_authenticated_identity(self, monkeypatch, capsys, tmp_path, probe):
        fake = _fake_es({"alpha": 50})
        self._run(probe, monkeypatch, capsys, ["alpha"], fake, tmp_path, ns="user-1")
        self._run(probe, monkeypatch, capsys, ["alpha"], fake, tmp_path, ns="user-2")
        assert len(fake.calls) == 2  # another account never shares an entry
        assert len(list(tmp_path.iterdir())) == 2  # two namespace directories

    def test_namespace_comes_from_tl_whoami_and_disables_cache_on_failure(self, monkeypatch, tmp_path, probe):
        def whoami_ok(cmd, **kw):
            assert cmd[:2] == ["tl", "whoami"]
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"user": {"id": 7, "email": "a@b"}}), stderr="")
        monkeypatch.setattr(probe.subprocess, "run", whoami_ok)
        monkeypatch.setattr(probe, "_CACHE_NS", None)
        ns_a = probe.cache_namespace()
        monkeypatch.setenv("TL_API_URL", "https://staging.example")
        monkeypatch.setattr(probe, "_CACHE_NS", None)
        assert probe.cache_namespace() not in (None, ns_a)  # endpoint is part of the identity
        monkeypatch.setattr(probe.subprocess, "run",
                            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="not logged in"))
        monkeypatch.setattr(probe, "_CACHE_NS", None)
        assert probe.cache_namespace() is None
        assert probe.cache_load(str(tmp_path), {"q": 1}, 24) is None
        probe.cache_store(str(tmp_path), {"q": 1}, {"x": 1})
        assert not any(tmp_path.iterdir())  # nothing written when identity is unknown

    def test_namespace_resolved_once_under_concurrency(self, monkeypatch, probe):
        calls = []
        def slow_whoami(cmd, **kw):
            calls.append(cmd)
            time.sleep(0.05)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"user": {"id": 7}}), stderr="")
        monkeypatch.setattr(probe.subprocess, "run", slow_whoami)
        monkeypatch.setattr(probe, "_CACHE_NS", None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda _: probe.cache_namespace(), range(6)))
        assert len(calls) == 1 and len(set(results)) == 1 and results[0]

    def test_no_cache_flag(self, monkeypatch, capsys, tmp_path, probe):
        fake = _fake_es({"alpha": 50})
        self._run(probe, monkeypatch, capsys, ["--no-cache", "alpha"], fake, tmp_path)
        self._run(probe, monkeypatch, capsys, ["--no-cache", "alpha"], fake, tmp_path)
        assert len(fake.calls) == 2
        assert not any(tmp_path.iterdir())

    def test_transient_failure_retried_once(self, monkeypatch, capsys, tmp_path, probe):
        monkeypatch.setattr(probe, "RETRY_PAUSE", 0)
        fake = _fake_es({"alpha": 50}, fail_first=lambda body: True)
        out = self._run(probe, monkeypatch, capsys, ["--no-cache", "alpha"], fake, tmp_path)
        assert len(fake.calls) == 2
        assert out["failed"] == [] and out["keywords"][0]["count"] == 50


# ---------------------------------------------------------------- fetch_context

class TestFetchContextParallel:
    def test_order_kept_and_errors_recorded(self, monkeypatch, capsys, ctx):
        monkeypatch.setattr(ctx, "RETRY_PAUSE", 0)

        def run(cmd, input=None, **kw):
            body = json.loads(input)
            cid = next(f["term"]["channel.id"] for f in body["query"]["bool"]["filter"] if "channel.id" in f["term"])
            if cid == 2:
                return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")
            row = {"id": f"v{cid}", "title": f"kw hit {cid}", "summary": ""}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"results": [row], "total": 1}), stderr="")

        monkeypatch.setattr(ctx.subprocess, "run", run)
        monkeypatch.setattr(ctx.sys, "argv", ["fetch_context.py", "--channels", "3,2,1", "--no-cache",
                                              "--fields", "title", "--workers", "3", "kw"])
        ctx.main()
        out = json.loads(capsys.readouterr().out)
        assert [o["channel_id"] for o in out] == [3, 2, 1]
        assert out[1]["error"].startswith("tl db es failed") and out[1]["snippets"] == []
        assert out[0]["match_count"] == 1 and out[0]["snippets"][0]["keyword"] == "kw"
