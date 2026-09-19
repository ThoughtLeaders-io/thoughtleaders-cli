"""Keyword workflows preserve evidence and error semantics across providers."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "skills/tl-keyword-research/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(f"transport_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["probe", "fetch_context", "search_channels", "search_videos"])
def test_query_preserves_complete_evidence(name, monkeypatch):
    module = load(name)
    body = {"size": 1, "query": {"match_all": {}}}
    envelope = {
        "results": [{"id": "1:abc", "highlight": {"transcript": ["a quote"]}}],
        "total": 42,
        "aggregations": {"distinct_channels": {"value": 12}},
        "usage": {"credits_charged": 3},
        "limit": 1,
        "offset": 0,
    }
    calls = []

    def query(engine, request, **kwargs):
        calls.append((engine, request, kwargs))
        return envelope

    monkeypatch.setattr(module.tl_data, "query", query)
    assert module.run_es(body) is envelope
    assert calls == [("es", body, {"timeout": getattr(module, "PROBE_TIMEOUT", 90)})]


@pytest.mark.parametrize("name", ["probe", "fetch_context", "search_channels", "search_videos"])
def test_suspension_is_not_a_failed_or_empty_search(name, monkeypatch):
    module = load(name)

    class Suspend(BaseException):
        pass

    def suspend(*args, **kwargs):
        raise Suspend()

    monkeypatch.setattr(module.tl_data, "query", suspend)
    with pytest.raises(Suspend):
        module.run_es({})


@pytest.mark.parametrize("exit_code", [2, 4, 5])
def test_probe_access_errors_abort_before_emitting_results(exit_code, monkeypatch, capsys):
    module = load("probe")
    error = module.tl_data.DataError("access or evidence unavailable")
    error.exit_code = exit_code

    def query(*args, **kwargs):
        raise error

    monkeypatch.setattr(module.tl_data, "query", query)
    monkeypatch.setattr(module.tl_data, "prefetch", lambda requests: None)
    monkeypatch.setattr(module.sys, "argv", ["probe.py", "--no-recency", "test"])
    with pytest.raises(SystemExit) as result:
        module.main()
    assert result.value.code == exit_code
    assert capsys.readouterr().out == ""


def test_probe_batches_before_fetching_and_matches_cli_output(monkeypatch, capsys):
    module = load("probe")
    envelopes = {
        "solar": {"total": 8, "results": [], "aggregations": {"distinct_channels": {"value": 3}}},
        "wind": {"total": 2, "results": [], "aggregations": {"distinct_channels": {"value": 1}}},
    }

    def term(body):
        return body["query"]["bool"]["must"][0]["multi_match"]["query"]

    def cli(cmd, *, input, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, json.dumps(envelopes[term(json.loads(input))]), "")

    monkeypatch.delenv("TL_MCP_SESSION", raising=False)
    monkeypatch.setattr(module.tl_data.subprocess, "run", cli)
    monkeypatch.setattr(module.sys, "argv", ["probe.py", "--no-recency", "--samples", "0", "solar", "wind"])
    module.main()
    cli_result = json.loads(capsys.readouterr().out)
    events = []

    def prefetch(requests):
        events.append(("prefetch", [term(item["query"]) for item in requests]))
        assert all(item["engine"] == "es" and not item["pricing"] and not item["include_highlight"]
                   for item in requests)

    def receipts(engine, body, **kwargs):
        assert engine == "es"
        events.append(("query", term(body)))
        return envelopes[term(body)]

    monkeypatch.setattr(module.tl_data, "prefetch", prefetch)
    monkeypatch.setattr(module.tl_data, "query", receipts)
    module.main()
    assert json.loads(capsys.readouterr().out) == cli_result
    assert events == [("prefetch", ["solar", "wind"]), ("query", "solar"), ("query", "wind")]


def test_probe_real_receipts_resume_without_cli_and_preserve_output(monkeypatch, capsys, tmp_path):
    module = load("probe")
    envelope = {
        "results": [{"title": "Solar power", "channel": {"id": 10}}],
        "total": 9,
        "aggregations": {"distinct_channels": {"value": 4}},
        "usage": {"credits_charged": 2},
    }

    def cli(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, json.dumps(envelope), "")

    monkeypatch.delenv("TL_MCP_SESSION", raising=False)
    monkeypatch.setattr(module.tl_data.subprocess, "run", cli)
    monkeypatch.setattr(module.sys, "argv", ["probe.py", "--no-recency", "solar", "wind"])
    module.main()
    expected = json.loads(capsys.readouterr().out)
    (tmp_path / "session.json").write_text(json.dumps({"id": "keyword-test", "source": "fixture-v1"}), encoding="utf-8")
    (tmp_path / "responses").mkdir()
    monkeypatch.setenv("TL_MCP_SESSION", str(tmp_path))

    def no_cli(*args, **kwargs):
        pytest.fail("MCP execution must not invoke the local CLI")

    monkeypatch.setattr(module.tl_data.subprocess, "run", no_cli)
    with pytest.raises(module.tl_data.PendingRequest) as pending:
        module.main()
    assert capsys.readouterr().out == ""
    assert len(pending.value.requests) == 2
    for req in pending.value.requests:
        assert req["tool"] == "tl_db_es"
        receipt = {"request": req, "response": {"structuredContent": envelope}}
        (tmp_path / "responses" / (req["id"] + ".json")).write_text(json.dumps(receipt), encoding="utf-8")
    module.main()
    assert json.loads(capsys.readouterr().out) == expected
