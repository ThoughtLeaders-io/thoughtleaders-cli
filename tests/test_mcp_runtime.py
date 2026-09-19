"""Behavioral contracts for resumable processing without local CLI access."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SHARED = Path(__file__).resolve().parents[1] / "skills" / "_shared"
sys.path.insert(0, str(SHARED))
import tl_data

SPEC = importlib.util.spec_from_file_location("mcp_run", SHARED / "mcp_run.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.delenv("TL_MCP_SESSION", raising=False)
    monkeypatch.setattr(tl_data, "_cli", lambda *a, **k: pytest.fail("MCP must never call CLI"))
    script = tmp_path / "processor.py"
    script.write_text('import tl_data, json\nprint(json.dumps(tl_data.query("es", {"size": 1})))\n', encoding="utf-8")
    return tmp_path / "session", script


def record(session, request, response):
    path = session.parent / "response.json"
    path.write_text(json.dumps(response), encoding="utf-8")
    return runner.ingest(session, request["id"], path)


def test_run_pause_ingest_resume_preserves_complete_envelope(workflow):
    session, script = workflow
    first = runner.run(session, script, [])
    assert first["phase"] == "needs_tools"
    assert first["requests"][0]["tool"] == "tl_whoami"
    record(session, first["requests"][0], {"user": {"id": 1}})
    second = runner.run(session, script, [])
    req = second["requests"][0]
    assert req["tool"] == "tl_db_es"
    evidence = {"results": [{"id": 5}], "total": 6, "aggregations": {"n": {"value": 6}}, "next_offset": 1}
    record(session, req, {"structuredContent": evidence})
    third = runner.run(session, script, [])
    assert json.loads(Path(third["output_path"]).read_text()) == evidence
    assert runner.run(session, script, [])["reused"] is True


def test_error_receipt_stays_error(workflow):
    session, script = workflow
    pending = runner.run(session, script, [])
    record(session, pending["requests"][0], {"error": "Not allowed", "code": "forbidden"})
    with pytest.raises(tl_data.DataError) as exc:
        runner.run(session, script, [])
    assert exc.value.exit_code == 5
    assert not list(session.glob("*.output.txt"))


def test_transient_retry_is_explicit_bounded_and_preserves_history(workflow):
    session, script = workflow
    req = runner.run(session, script, [])["requests"][0]
    error = {"isError": True, "content": [{"type": "text", "text": "Internal error"}]}
    for attempt in range(2):
        record(session, req, error)
        assert runner.retry(session, req["id"])["retry"] == attempt + 1
    record(session, req, error)
    with pytest.raises(tl_data.DataError, match="limit"):
        runner.retry(session, req["id"])
    assert len(list((session / "failed-attempts").glob("*.json"))) == 2


def test_retry_recomputes_previously_completed_partial_output(workflow):
    session, script = workflow
    script.write_text('import tl_data\ntry:\n print(tl_data.query("es", {"size": 1}))\nexcept tl_data.DataError:\n print("partial")\n', encoding="utf-8")
    pending = runner.run(session, script, [])
    record(session, pending["requests"][0], {"user": {"id": 1}})
    req = runner.run(session, script, [])["requests"][0]
    record(session, req, {"error": "Temporarily unavailable", "code": "upstream_error"})
    partial = runner.run(session, script, [])
    assert Path(partial["output_path"]).read_text() == "partial\n"
    runner.retry(session, req["id"])
    record(session, req, {"results": [{"id": 7}]})
    completed = runner.run(session, script, [])
    assert "7" in Path(completed["output_path"]).read_text()


@pytest.mark.parametrize("code,expected", [("unauthenticated", 2), ("premium_fields_blocked", 5), ("invalid_input", 1), ("upstream_error", 3)])
def test_real_error_codes_keep_failure_semantics(code, expected):
    with pytest.raises(tl_data.DataError) as exc:
        tl_data.normalize({"error": "Failure", "code": code})
    assert exc.value.exit_code == expected


@pytest.mark.parametrize("response", [{"user": {"id": 1}}, {"error": "No credits", "code": "insufficient_credits"}])
def test_success_and_access_denial_cannot_be_replaced(workflow, response):
    session, script = workflow
    req = runner.run(session, script, [])["requests"][0]
    record(session, req, response)
    with pytest.raises(tl_data.DataError):
        runner.retry(session, req["id"])


def test_duplicate_unknown_and_cross_session_receipts_rejected(workflow, tmp_path):
    session, script = workflow
    req = runner.run(session, script, [])["requests"][0]
    record(session, req, {"user": {"id": 1}})
    with pytest.raises(tl_data.DataError, match="already"):
        record(session, req, {})
    with pytest.raises(tl_data.DataError, match="Unknown"):
        record(session, {"id": "unknown"}, {})
    other = tmp_path / "other"
    other_req = runner.run(other, script, [])["requests"][0]
    assert req["id"] != other_req["id"]
    with pytest.raises(tl_data.DataError, match="Unknown"):
        record(other, req, {})


def test_source_change_invalidates_session(workflow):
    session, script = workflow
    runner.run(session, script, [])
    script.write_text('print("changed")\n', encoding="utf-8")
    with pytest.raises(tl_data.DataError, match="code changed"):
        runner.run(session, script, [])


@pytest.mark.parametrize("result", [{"_upgrade_required": {"fields": ["transcript"]}}, {"quota_notice": "partial results"}])
def test_withheld_or_truncated_evidence_is_not_empty(result):
    with pytest.raises(tl_data.DataError) as exc:
        tl_data.normalize({"structuredContent": result})
    assert exc.value.exit_code == 5


def test_transport_error_cannot_be_hidden_by_success_payload():
    with pytest.raises(tl_data.DataError):
        tl_data.normalize({"isError": True, "structuredContent": {"results": []}})


def test_transport_error_keeps_credit_failure_classification():
    with pytest.raises(tl_data.DataError) as exc:
        tl_data.normalize({"isError": True, "structuredContent": {"error": "No credits", "code": "insufficient_credits"}})
    assert exc.value.exit_code == 4


def test_missing_query_payload_is_not_zero_matches(monkeypatch):
    monkeypatch.delenv("TL_MCP_SESSION", raising=False)
    monkeypatch.setattr(tl_data, "_cli", lambda *a, **k: {})
    with pytest.raises(tl_data.DataError, match="missing evidence"):
        tl_data.query("es", {"size": 1})


def test_text_json_mcp_result_preserves_highlights():
    body = {"results": [{"id": 1, "highlight": {"transcript": ["evidence"]}}], "total": 1}
    assert tl_data.normalize({"content": [{"type": "text", "text": json.dumps(body)}]}) == body


def test_prefetch_deduplicates_and_suspends_bounded_batch(workflow, monkeypatch):
    session, script = workflow
    runner.run(session, script, [])
    monkeypatch.setenv("TL_MCP_SESSION", str(session))
    with pytest.raises(tl_data.PendingRequest) as pending:
        tl_data.prefetch([{"engine": "es", "query": {"size": 1}}] * 2)
    assert len(pending.value.requests) == 1


def test_input_and_args_get_separate_output(workflow):
    session, script = workflow
    script.write_text('import sys\nprint(sys.stdin.read() + sys.argv[1])\n', encoding="utf-8")
    pending = runner.run(session, script, ["first"])
    record(session, pending["requests"][0], {"user": {"id": 1}})
    first = runner.run(session, script, ["first"])
    second = runner.run(session, script, ["second"])
    assert first["output_path"] != second["output_path"]
    assert Path(second["output_path"]).read_text() == "second\n"


def test_changed_classifier_file_does_not_reuse_old_output(workflow, tmp_path):
    session, script = workflow
    script.write_text('import pathlib,sys\nprint(pathlib.Path(sys.argv[1]).read_text())\n', encoding="utf-8")
    evidence = tmp_path / "labels.json"
    evidence.write_text("first", encoding="utf-8")
    pending = runner.run(session, script, [str(evidence)])
    record(session, pending["requests"][0], {"user": {"id": 1}})
    first = runner.run(session, script, [str(evidence)])
    evidence.write_text("revised", encoding="utf-8")
    second = runner.run(session, script, [str(evidence)])
    assert first["output_path"] != second["output_path"]
    assert Path(second["output_path"]).read_text() == "revised\n"
