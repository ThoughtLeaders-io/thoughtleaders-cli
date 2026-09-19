"""Full shared authenticity processing across CLI and recorded MCP evidence."""
import copy
import importlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/tl-channel-authenticity/scripts"
SHARED = ROOT / "skills/_shared"


def fixture_response(tool, arguments):
    """Raw data fixtures only; scoring, selection and orchestration stay real."""
    if tool == "tl_whoami":
        return {"user": {"id": 7}, "organization": {"id": 8}}
    if tool == "tl_channels_similar":
        rows = [{"id": 2}, {"id": 3}, {"id": 4}]
    elif tool == "tl_db_pg":
        sql = arguments["query"]
        if "FROM thoughtleaders_channel" in sql:
            rows = [{"id": 1, "channel_name": "Fixture Creator", "subscribers": 100000,
                     "content_category": 1, "language": "en", "url": "https://youtube.com/@fixture"}]
        elif "FROM thoughtleaders_adlink" in sql:
            rows = []
        else:
            pytest.fail(f"Uncovered PG fixture: {sql}")
    elif tool == "tl_db_fb":
        sql = arguments["query"]
        if "FROM article_metrics" in sql:
            rows = [{"age": age, "view_count": views, "like_count": views // 20,
                     "comment_count": views // 100}
                    for age, views in [(1, 1500), (2, 2500), (5, 4500), (10, 6500), (20, 8500), (30, 10000)]]
        elif "FROM channel_metrics" in sql:
            rows = [{"scrape_date": f"2026-08-{i + 1:02}", "total_views": 100000 + i * 10000,
                     "subscribers": 95000 + i * 100} for i in range(8)]
        else:
            pytest.fail(f"Uncovered FB fixture: {sql}")
    elif tool == "tl_db_es":
        terms = {key: value for clause in arguments["query"]["query"]["bool"]["must"]
                 for key, value in clause.get("term", {}).items()}
        channel = terms["channel.id"]
        kind = terms.get("content_type", "longform")
        count = 3 if kind == "short" else 10
        rows = [{"id": f"{channel}:{kind}{i}", "title": f"Fixture {kind} episode {i}",
                 "publication_date": f"2026-08-{20-i:02}", "views": 10000 + i * 100,
                 "likes": 500 + i * 5, "comments": 100 + i,
                 "duration": 45 if kind == "short" else 900, "content_type": kind,
                 "url": f"https://youtube.com/watch?v={kind}{i}"} for i in range(count)]
    else:
        pytest.fail(f"Unexpected tool: {tool}")
    return {"results": rows, "total": len(rows), "usage": {"credits_charged": 1}}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    monkeypatch.delenv("TL_MCP_SESSION", raising=False)
    monkeypatch.syspath_prepend(str(SHARED))
    monkeypatch.syspath_prepend(str(SCRIPTS))
    names = {path.stem for path in SCRIPTS.glob("*.py")} - {"tl_data", "mcp_run"}
    previous = {name: sys.modules[name] for name in names if name in sys.modules}
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)
    seam_spec = importlib.util.spec_from_file_location("tl_cli", SCRIPTS / "tl_cli.py")
    seam = importlib.util.module_from_spec(seam_spec)
    monkeypatch.setitem(sys.modules, "tl_cli", seam)
    seam_spec.loader.exec_module(seam)
    orchestrator = importlib.import_module("analyze_channel")
    peer = importlib.import_module("peer_cohort")
    runner_spec = importlib.util.spec_from_file_location("workflow_runner", SHARED / "mcp_run.py")
    runner = importlib.util.module_from_spec(runner_spec)
    runner_spec.loader.exec_module(runner)
    monkeypatch.setattr(orchestrator, "OUT_DIR", tmp_path / "cli")
    monkeypatch.setattr(peer, "CACHE", tmp_path / "cli-peer-cache.json")
    scraped = []

    def comments(video_id, cap):
        scraped.append(video_id)
        return [{"cid": f"{video_id}-{i}", "text": f"I tested the explanation from {video_id} and learned detail {i}.",
                 "author": f"Viewer-{video_id}-{i}", "votes": i, "replies": 1,
                 "time": None, "is_reply": False, "is_creator": False, "hearted": i == 0}
                for i in range(3)]

    monkeypatch.setattr(orchestrator.comment_scraper, "_scrape_ytdlp", comments)
    yield runner, orchestrator, peer, seam.tl_data, scraped
    for name in names:
        sys.modules.pop(name, None)
    sys.modules.update(previous)


def classifications(state_path, directory):
    state = json.loads(Path(state_path).read_text(encoding="utf-8"))
    batch = state["group_c"]["llm_batch"]
    assert batch
    paths = []
    for number in (1, 2):
        path = directory / f"classifier-{number}.json"
        path.write_text(json.dumps([{"i": row["i"], "label": "organic"} for row in batch]), encoding="utf-8")
        paths.append(str(path))
    return paths


def comparable(state):
    result = copy.deepcopy(state)
    # Replay consults the session's computed baseline cache; cache provenance
    # differs but all domain evidence and scores must remain identical.
    baseline = result["group_a"]["metrics"]["peer_baseline"]
    baseline.pop("cached", None)
    baseline.pop("_ts", None)
    return result


def test_full_collect_receipts_classify_finalize_matches_cli(runtime, monkeypatch, tmp_path):
    runner, orchestrator, peer, data, scraped = runtime

    def cli(args, *, input_text=None, **kwargs):
        if args[0] == "whoami":
            return fixture_response("tl_whoami", {})
        if args[:2] == ["channels", "similar"]:
            return fixture_response("tl_channels_similar", {})
        assert args[0] == "db"
        query = json.loads(input_text) if args[1] == "es" else input_text
        return fixture_response("tl_db_" + args[1], {"query": query})

    monkeypatch.setattr(data, "_cli", cli)
    cli_collection = orchestrator.collect("1")
    cli_labels = classifications(cli_collection["state_path"], tmp_path)
    cli_final = orchestrator.finalize(cli_collection["state_path"], cli_labels)
    cli_state = json.loads(Path(cli_final["final_json"]).read_text(encoding="utf-8"))
    assert len(scraped) == 10
    scraped.clear()
    session = tmp_path / "mcp-session"
    monkeypatch.setattr(peer, "CACHE", session / "peer-cohort-cache.json")

    def no_cli(*args, **kwargs):
        pytest.fail("Full MCP workflow attempted to invoke CLI")

    monkeypatch.setattr(data, "_cli", no_cli)
    calls = []
    for _ in range(50):
        outcome = runner.run(session, SCRIPTS / "analyze_channel.py", ["1"])
        if outcome["phase"] == "complete":
            break
        assert outcome["phase"] == "needs_tools"
        assert not list(session.glob("*.output.txt"))
        for request in outcome["requests"]:
            assert request["id"] not in [item["id"] for item in calls]
            calls.append(request)
            response = tmp_path / "tool-response.json"
            response.write_text(json.dumps({"structuredContent": fixture_response(request["tool"], request["arguments"])}), encoding="utf-8")
            runner.ingest(session, request["id"], response)
    else:
        pytest.fail("Full collection did not finish within its bounded receipt loop")
    collection = json.loads(Path(outcome["output_path"]).read_text(encoding="utf-8"))
    assert collection["phase"] == "collect_done"
    assert len(scraped) == 10
    assert {item["tool"] for item in calls} == {"tl_whoami", "tl_channels_similar", "tl_db_pg", "tl_db_es", "tl_db_fb"}
    labels = classifications(collection["state_path"], session)
    final = runner.run(session, SCRIPTS / "analyze_channel.py", ["--finalize", collection["state_path"], *labels])
    assert final["phase"] == "complete"
    markdown = Path(final["output_path"]).read_text(encoding="utf-8")
    assert "Fixture Creator" in markdown
    final_paths = list(session.glob("*.final.json"))
    assert len(final_paths) == 1
    mcp_state = json.loads(final_paths[0].read_text(encoding="utf-8"))
    assert mcp_state["group_c"]["metrics"]["llm_passes"] == 2
    assert len(mcp_state["group_b"]["metrics"]["videos"]) == 10
    assert mcp_state["group_a"]["metrics"]["peer_baseline"]["n_peers"] == 3
    assert comparable(mcp_state) == comparable(cli_state)
    assert runner.run(session, SCRIPTS / "analyze_channel.py", ["--finalize", collection["state_path"], *labels])["reused"]
