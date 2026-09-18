"""Batch protocol: snapshot + manifest + batch files + repairs + passes.

Covers select_keywords.py artifact mode end to end (emit → partial verdicts →
repair → apply) and the kw_batches invariants the judge agents rely on.
"""
import importlib.util
import json
import os
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "tl-keyword-research" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kwp_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sk():
    return _load("select_keywords")


@pytest.fixture
def kb():
    return _load("kw_batches")


def _probe():
    return {"operator": "OR", "level": "topic", "keywords": [
        {"keyword": "tiktok shop", "count": 100, "samples": [
            {"title": f"TikTok Shop {n}", "summary": "sell", "channel_id": n, "url": f"u{n}"} for n in range(5)]},
        {"keyword": "tiktok", "count": 9000, "samples": [
            {"title": f"TikTok dance {n}", "summary": "lol", "channel_id": 100 + n, "url": f"d{n}"} for n in range(3)]},
    ], "dropped": []}


def _run(sk, monkeypatch, capsys, argv):
    monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py"] + argv)
    code, msg = 0, ""
    try:
        sk.main()
    except SystemExit as exc:  # sys.exit("message") only prints at interpreter exit
        code = exc.code if isinstance(exc.code, int) else 1
        msg = "" if isinstance(exc.code, int) or exc.code is None else str(exc.code)
    out = capsys.readouterr()
    return code, out.out, out.err + msg


def _write_verdicts(batch_path, decide, only_ids=None):
    b = json.loads(Path(batch_path).read_text())
    ids = [i for i in b["ids"] if only_ids is None or i in only_ids]
    Path(b["verdict_path"]).write_text(json.dumps([{"i": i, "relevant": decide(i)} for i in ids]))
    return b


class TestEmit:
    def test_emit_writes_snapshot_manifest_and_batches(self, sk, monkeypatch, capsys, tmp_path):
        probe = tmp_path / "probe.json"; probe.write_text(json.dumps(_probe()))
        out_dir = tmp_path / "val1"
        code, out, _ = _run(sk, monkeypatch, capsys, ["--emit-batch", "--probe-file", str(probe),
                                                      "--intent", "selling on TikTok Shop",
                                                      "--out-dir", str(out_dir), "--chunk", "3"])
        assert code == 0
        s = json.loads(out)
        assert s["judge"] == "relevance" and s["item_count"] == 8
        assert [b["count"] for b in s["batches"]] == [3, 3, 2]
        m = json.loads((out_dir / "manifest.json").read_text())
        assert m["item_ids"] == list(range(8)) and m["passes"] == ["p1"]
        assert json.loads((out_dir / "probe.snapshot.json").read_text()) == _probe()
        b0 = json.loads(Path(s["batches"][0]["path"]).read_text())
        assert b0["intent"] == "selling on TikTok Shop" and b0["judge"] == "relevance"
        assert b0["ids"] == [0, 1, 2] and b0["last_id"] == 2 and b0["count"] == 3
        assert [it["i"] for it in b0["items"]] == [0, 1, 2] and b0["items"][0]["keyword"] == "tiktok shop"
        assert b0["verdict_path"].endswith("batch_p1_000.verdict.json")

    def test_intent_required_and_empty_probe_ok(self, sk, monkeypatch, capsys, tmp_path):
        probe = tmp_path / "probe.json"; probe.write_text(json.dumps(_probe()))
        code, _, _ = _run(sk, monkeypatch, capsys, ["--emit-batch", "--probe-file", str(probe), "--out-dir", str(tmp_path / "x")])
        assert code != 0
        empty = tmp_path / "empty.json"; empty.write_text(json.dumps({"level": "topic", "keywords": []}))
        code, out, _ = _run(sk, monkeypatch, capsys, ["--emit-batch", "--probe-file", str(empty), "--intent", "x",
                                                      "--out-dir", str(tmp_path / "e")])
        assert code == 0 and json.loads(out)["batches"] == []

    def test_emit_refuses_existing_run_dir(self, sk, monkeypatch, capsys, tmp_path):
        probe = tmp_path / "probe.json"; probe.write_text(json.dumps(_probe()))
        args = ["--emit-batch", "--probe-file", str(probe), "--intent", "x", "--out-dir", str(tmp_path / "v")]
        assert _run(sk, monkeypatch, capsys, args)[0] == 0
        code, _, err = _run(sk, monkeypatch, capsys, args)
        assert code != 0 and "already holds a judge run" in err

    def test_byte_cap_splits_batches(self, kb):
        items = {i: {"i": i, "title": "x" * 1000} for i in range(10)}
        assert [len(b) for b in kb.chunk_ids(list(range(10)), items, 40, 2500)] == [2, 2, 2, 2, 2]


class TestApplyRepairAndPasses:
    def _emit(self, sk, monkeypatch, capsys, tmp_path, chunk="3"):
        probe = tmp_path / "probe.json"; probe.write_text(json.dumps(_probe()))
        out_dir = tmp_path / "val1"
        _, out, _ = _run(sk, monkeypatch, capsys, ["--emit-batch", "--probe-file", str(probe), "--intent", "shop",
                                                   "--out-dir", str(out_dir), "--chunk", chunk])
        return out_dir, json.loads(out)["batches"]

    def test_unjudged_batches_are_reported_not_repaired(self, sk, monkeypatch, capsys, tmp_path):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path)
        code, out, err = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 2
        s = json.loads(out)
        assert s["status"] == "incomplete" and s["batches"] == []  # nothing to repair yet
        assert s["passes"][0]["unread_batches"] == [b["batch_id"] for b in batches]

    def test_truncated_reply_yields_repair_then_completes(self, sk, monkeypatch, capsys, tmp_path):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path)
        decide = lambda i: i < 5  # shop samples on-topic, dance samples off
        _write_verdicts(batches[0]["path"], decide)
        _write_verdicts(batches[1]["path"], decide, only_ids={3})  # truncated: 4, 5 missing
        _write_verdicts(batches[2]["path"], decide)
        code, out, _ = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 2
        s = json.loads(out)
        assert s["passes"] == [{"pass_id": "p1", "missing": 2, "unread_batches": [], "missing_ids": [4, 5]}]
        assert len(s["batches"]) == 1 and s["batches"][0]["kind"] == "repair"
        rep = json.loads(Path(s["batches"][0]["path"]).read_text())
        assert rep["ids"] == [4, 5] and rep["pass_id"] == "p1" and rep["batch_id"] == "p1_r000"
        # a second --apply before judging the repair does not spawn more repairs
        code, out, _ = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 2 and json.loads(out)["batches"] == []
        _write_verdicts(rep["verdict_path"] and s["batches"][0]["path"], decide)
        code, out, _ = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 0
        res = json.loads(out)
        assert [k["keyword"] for k in res["kept"]] == ["tiktok shop"]
        assert [d["keyword"] for d in res["dropped"]] == ["tiktok"]
        assert res["fitness"]["samples"] == 8 and res["fitness"]["judged"] == 8
        assert res["fitness"]["on_topic"] == 5 and res["fitness"]["relevance_share"] == 0.625
        assert res["fitness"]["worst_offenders"][0]["keyword"] == "tiktok"

    def test_second_pass_majority_votes(self, sk, monkeypatch, capsys, tmp_path):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path, chunk="10")
        _write_verdicts(batches[0]["path"], lambda i: True)  # p1 says everything is relevant
        code, out, _ = _run(sk, monkeypatch, capsys, ["--add-pass", "--manifest", str(out_dir)])
        assert code == 0 and json.loads(out)["pass_id"] == "p2"
        p2 = json.loads(out)["batches"]
        assert len(p2) == 1 and p2[0]["batch_id"] == "p2_000"
        code, out, _ = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 2  # p2 not judged yet
        _write_verdicts(p2[0]["path"], lambda i: False)  # p2 disagrees on everything → ties → drop
        code, out, _ = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code == 0 and json.loads(out)["kept"] == []

    def test_conflicting_duplicate_within_pass_is_fatal(self, sk, monkeypatch, capsys, tmp_path):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path, chunk="10")
        b = json.loads(Path(batches[0]["path"]).read_text())
        Path(b["verdict_path"]).write_text(json.dumps([{"i": 0, "relevant": True}, {"i": 0, "relevant": False}]
                                                      + [{"i": i, "relevant": True} for i in range(1, 8)]))
        code, _, err = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code != 0 and "conflicting" in err

    @pytest.mark.parametrize("bad", [{"i": 0, "relevant": "false"}, {"i": "0", "relevant": True},
                                     {"i": 99, "relevant": True}, "not an object"])
    def test_malformed_entries_are_rejected(self, sk, monkeypatch, capsys, tmp_path, bad):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path, chunk="10")
        b = json.loads(Path(batches[0]["path"]).read_text())
        Path(b["verdict_path"]).write_text(json.dumps([bad]))
        code, _, err = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code != 0 and err

    def test_fenced_reply_is_rejected_not_parsed(self, sk, monkeypatch, capsys, tmp_path):
        out_dir, batches = self._emit(sk, monkeypatch, capsys, tmp_path, chunk="10")
        b = json.loads(Path(batches[0]["path"]).read_text())
        Path(b["verdict_path"]).write_text("```json\n[]\n```")
        code, _, err = _run(sk, monkeypatch, capsys, ["--apply", "--manifest", str(out_dir)])
        assert code != 0 and "could not read" in err


class TestLegacyStrictness:
    def test_string_false_rejected(self, sk, monkeypatch, capsys, tmp_path):
        v = tmp_path / "v.json"; v.write_text(json.dumps([{"i": 0, "relevant": "false"}]))
        monkeypatch.setattr(sk.sys.stdin, "isatty", lambda: False)
        monkeypatch.setattr(sk.sys.stdin, "read", lambda: json.dumps(_probe()))
        code, _, err = _run(sk, monkeypatch, capsys, ["--apply", str(v)])
        assert code != 0 and "JSON boolean" in err
