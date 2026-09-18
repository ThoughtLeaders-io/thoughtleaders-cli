"""fetch_context.py filter parity + classifier batches, classify_channels.py merge,
and probe.py measurement modes (residual / exclusion) — all with ES mocked."""
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "tl-keyword-research" / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"kwc_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def ctx(monkeypatch):
    m = _load("fetch_context")
    monkeypatch.setattr(m, "_NS", "test-identity")
    monkeypatch.setattr(m, "RETRY_PAUSE", 0)
    return m


@pytest.fixture
def cc():
    return _load("classify_channels")


@pytest.fixture
def probe(monkeypatch, tmp_path):
    m = _load("probe")
    monkeypatch.setattr(m, "_CACHE_NS", "test-identity")
    monkeypatch.setattr(m, "CACHE_DIR", str(tmp_path / "pc"))
    return m


def _main(mod, monkeypatch, capsys, argv):
    monkeypatch.setattr(mod.sys, "argv", [mod.__name__] + argv)
    code, msg = 0, ""
    try:
        mod.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
        msg = "" if isinstance(exc.code, int) or exc.code is None else str(exc.code)
    out = capsys.readouterr()
    return code, out.out, out.err + msg


def _cid(body):
    return next(f["term"]["channel.id"] for f in body["query"]["bool"]["filter"] if "channel.id" in f["term"])


def _es_fake(fail_ids=(), title="the creator economy is changing"):
    calls = []

    def run(cmd, input=None, **kw):
        if cmd[:2] == ["tl", "whoami"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"user": {"id": 1}}), stderr="")
        body = json.loads(input)
        calls.append(body)
        cid = _cid(body)
        if cid in fail_ids:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Server error (503): nope")
        row = {"id": f"v{cid}", "title": f"{title} #{cid}", "summary": "tips for creators"}
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"results": [row], "total": 3}), stderr="")

    run.calls = calls
    return run


GROUPS = {"operator": "AND", "default_content_fields": ["title", "summary"],
          "groups": [{"text": "creator economy", "content_fields": ["title"]},
                     {"text": '(changing | "is dying") +youtube'},
                     {"text": "scam", "exclude": True}]}


class TestFilterParity:
    def test_literal_terms(self, ctx):
        assert ctx.literal_terms('("fable 5" | fable5) -keto +launch') == ["fable 5", "fable5", "launch"]
        assert ctx.literal_terms('"creator economy"') == ["creator economy"]

    def test_literal_terms_negation_and_escapes(self, ctx):
        assert ctx.literal_terms('a -"bad phrase" b') == ["a", "b"]
        assert ctx.literal_terms('retire -(scam | "get rich") +(plan | "401k")') == ["retire", "plan", "401k"]
        assert ctx.literal_terms('"say \\"hello\\" world" -x') == ['say "hello" world']
        assert ctx.literal_terms('(inner -(deep | deeper) kept) | outer') == ["inner", "kept", "outer"]

    def test_anchors_respect_group_field_scope(self, ctx, monkeypatch, capsys, tmp_path):
        g = _write(tmp_path, {"groups": [{"text": "apple", "content_fields": ["title"]},
                                         {"text": "pension", "content_fields": ["title", "summary"]}]})
        def run(cmd, input=None, **kw):
            if cmd[:2] == ["tl", "whoami"]:
                return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"user": {"id": 1}}), stderr="")
            row = {"id": "v1", "title": "pension advice", "summary": "apple apple apple apple pension"}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"results": [row], "total": 1}), stderr="")
        monkeypatch.setattr(ctx.subprocess, "run", run)
        code, out, err = _main(ctx, monkeypatch, capsys, ["--groups-file", str(g), "--channels", "7", "--no-cache",
                                                          "--max-snippets", "3"])
        assert code == 0, err
        snips = json.loads(out)[0]["snippets"]
        assert all(not (s["keyword"] == "apple" and s["field"] == "summary") for s in snips)
        assert any(s["keyword"] == "pension" and s["field"] == "title" for s in snips)

    def test_groups_query_mirrors_search(self, ctx, monkeypatch, capsys, tmp_path):
        g = tmp_path / "groups.json"; g.write_text(json.dumps(GROUPS))
        fake = _es_fake()
        monkeypatch.setattr(ctx.subprocess, "run", fake)
        code, out, err = _main(ctx, monkeypatch, capsys, ["--groups-file", str(g), "--channels", "7",
                                                          "--no-cache", "--since", "2026-01-01"])
        assert code == 0, err
        b = fake.calls[0]["query"]["bool"]
        assert "must" in b  # operator AND from the file
        clauses = [c["simple_query_string"] for c in b["must"]]
        assert clauses[0] == {"query": '"creator economy"', "fields": ["title"], "default_operator": "and"}
        assert clauses[1]["fields"] == ["title", "summary"]  # default_content_fields
        assert b["must_not"][0]["simple_query_string"]["query"] == "scam"
        filt = fake.calls[0]["query"]["bool"]["filter"]
        assert {"term": {"channel.format": 4}} in filt and {"term": {"content_type": "longform"}} in filt
        assert {"range": {"publication_date": {"gte": "2026-01-01"}}} in filt
        snippets = json.loads(out)[0]["snippets"]
        assert snippets and snippets[0]["keyword"] == "creator economy"  # anchored on the literal, not the expression

    def test_channel_level_fields_rejected(self, ctx, tmp_path):
        with pytest.raises(SystemExit):
            ctx.load_groups_file(str(_write(tmp_path, {"groups": [{"text": "x", "content_fields": ["channel_description"]}]})), ["title"])


def _write(tmp_path, obj, name="g.json"):
    p = tmp_path / name; p.write_text(json.dumps(obj)); return p


class TestBatchesAndMerge:
    def _emit(self, ctx, monkeypatch, capsys, tmp_path, fail_ids=()):
        g = _write(tmp_path, GROUPS)
        chans = _write(tmp_path, {"channels": [{"channel_id": c, "tier": "recurring", "matching_uploads": 5,
                                                "name": f"ch{c}", "sponsorability": {"is_msn": c == 2}} for c in (1, 2, 3, 4)]}, "int.json")
        fake = _es_fake(fail_ids=fail_ids)
        monkeypatch.setattr(ctx.subprocess, "run", fake)
        out_dir = tmp_path / "ctx1"
        code, out, err = _main(ctx, monkeypatch, capsys, ["--groups-file", str(g), "--channels-file", str(chans),
                                                          "--emit-batches", "--topic", "creator economy news",
                                                          "--not", "get-rich-quick", "--out-dir", str(out_dir),
                                                          "--chunk", "3", "--no-cache", "--since", "2026-01-01",
                                                          "--content-type", "short"])
        assert code == 0, err
        return out_dir, json.loads(out), chans, fake

    def test_emit_refuses_existing_run_dir(self, ctx, monkeypatch, capsys, tmp_path):
        out_dir, s, chans, _ = self._emit(ctx, monkeypatch, capsys, tmp_path)
        g = tmp_path / "g.json"
        code, _, err = _main(ctx, monkeypatch, capsys, ["--groups-file", str(g), "--channels-file", str(chans),
                                                        "--emit-batches", "--topic", "t", "--out-dir", str(out_dir), "--no-cache"])
        assert code != 0 and "already holds a judge run" in err

    def test_tiers_and_max_channels_gate_the_fetch(self, ctx, monkeypatch, capsys, tmp_path):
        g = _write(tmp_path, GROUPS)
        chans = _write(tmp_path, {"channels": [{"channel_id": 1, "tier": "core"}, {"channel_id": 2, "tier": "one_off"},
                                               {"channel_id": 3, "tier": "recurring"}, {"channel_id": 4, "tier": "recurring"}]}, "int.json")
        fake = _es_fake()
        monkeypatch.setattr(ctx.subprocess, "run", fake)
        code, out, err = _main(ctx, monkeypatch, capsys, ["--groups-file", str(g), "--channels-file", str(chans),
                                                          "--tiers", "core,recurring", "--max-channels", "2", "--no-cache"])
        assert code == 0, err
        assert [o["channel_id"] for o in json.loads(out)] == [1, 3]

    def test_emit_excludes_failed_channels_and_indexes_items(self, ctx, monkeypatch, capsys, tmp_path):
        out_dir, s, _, _ = self._emit(ctx, monkeypatch, capsys, tmp_path, fail_ids=(3,))
        assert s["judge"] == "context" and s["item_count"] == 3
        assert s["failed_channels"] == [{"channel_id": 3, "error": s["failed_channels"][0]["error"]}]
        assert [b["count"] for b in s["batches"]] == [3]
        b = json.loads(Path(s["batches"][0]["path"]).read_text())
        assert b["topic"] == "creator economy news" and b["not"] == "get-rich-quick"
        assert [it["channel_id"] for it in b["items"]] == [1, 2, 4] and [it["i"] for it in b["items"]] == [0, 1, 2]

    def test_retry_failed_appends_new_batch_with_saved_scope(self, ctx, monkeypatch, capsys, tmp_path):
        out_dir, s, _, first = self._emit(ctx, monkeypatch, capsys, tmp_path, fail_ids=(3,))
        fake = _es_fake()  # now it works
        monkeypatch.setattr(ctx.subprocess, "run", fake)
        code, out, err = _main(ctx, monkeypatch, capsys, ["--retry-failed", str(out_dir), "--no-cache"])
        assert code == 0, err
        # the retry ran the ORIGINAL query: same date window, content type, groups and operator
        orig = [c for c in first.calls if _cid(c) == 3][0]
        assert fake.calls[0]["query"] == orig["query"]
        assert {"term": {"content_type": "short"}} in fake.calls[0]["query"]["bool"]["filter"]
        r = json.loads(out)
        assert r["retried"] == 1 and r["failed_channels"] == []
        assert r["batches"][0]["batch_id"] == "p1_001" and r["batches"][0]["count"] == 1
        m = json.loads((out_dir / "manifest.json").read_text())
        assert m["item_ids"] == [0, 1, 2, 3] and m["failed_channels"] == []

    def test_merge_with_repairs_and_tiers(self, ctx, cc, monkeypatch, capsys, tmp_path):
        out_dir, s, chans, _ = self._emit(ctx, monkeypatch, capsys, tmp_path, fail_ids=(4,))
        b = json.loads(Path(s["batches"][0]["path"]).read_text())
        # truncated reply: channel 3 (i=2) missing
        Path(b["verdict_path"]).write_text(json.dumps([
            {"i": 0, "channel_id": 1, "verdict": "on_topic", "confidence": "high", "evidence_quote": "creator economy",
             "adjacent_terms": ["mrbeast", "Sponsorships"], "notes": ""},
            {"i": 1, "channel_id": 2, "verdict": "off_topic", "confidence": "medium", "evidence_quote": "", "adjacent_terms": [], "notes": "crypto"}]))
        code, out, err = _main(cc, monkeypatch, capsys, ["--manifest", str(out_dir), "--intensity", str(chans)])
        assert code == 2
        rep = json.loads(out)["batches"]
        assert len(rep) == 1 and rep[0]["kind"] == "repair"
        rb = json.loads(Path(rep[0]["path"]).read_text())
        assert rb["ids"] == [2] and rb["items"][0]["channel_id"] == 3
        Path(rb["verdict_path"]).write_text(json.dumps([{"i": 2, "channel_id": 3, "verdict": "mixed", "confidence": "low",
                                                         "evidence_quote": "", "adjacent_terms": ["mrbeast"], "notes": ""}]))
        code, out, err = _main(cc, monkeypatch, capsys, ["--manifest", str(out_dir), "--intensity", str(chans)])
        assert code == 0, err
        res = json.loads(out)
        assert [c["channel_id"] for c in res["channels"]] == [1, 3]        # on_topic first, then mixed
        assert res["channels"][0]["tier"] == "recurring" and res["channels"][0]["sponsorability"] == {"is_msn": False}
        assert [c["channel_id"] for c in res["excluded"]] == [2]
        assert res["not_validated"]["fetch_failed"][0]["channel_id"] == 4
        assert res["not_validated"]["not_fetched"] == []
        assert res["adjacent_terms"][0] == {"term": "mrbeast", "channels": [1, 3], "mentions": 2}
        assert res["verdicts"] == {"on_topic": 1, "off_topic": 1, "mixed": 1}

    def test_metadata_comes_from_an_agreeing_pass(self, ctx, cc, monkeypatch, capsys, tmp_path):
        out_dir, s, chans, _ = self._emit(ctx, monkeypatch, capsys, tmp_path)
        items = [it for b in s["batches"] for it in json.loads(Path(b["path"]).read_text())["items"]]
        def verdicts(sub, verdict, note, terms):
            return [{"i": it["i"], "channel_id": it["channel_id"], "verdict": verdict, "confidence": "high",
                     "evidence_quote": note, "adjacent_terms": terms, "notes": note} for it in sub]
        for b in s["batches"]:
            sub = json.loads(Path(b["path"]).read_text())["items"]
            Path(b["verdict_path"]).write_text(json.dumps(verdicts(sub, "off_topic", "only sports betting", ["betting"])))
        # two more passes through the protocol module (what --add-pass would do)
        kb = _load("kw_batches")
        man = kb.load_manifest(str(out_dir))
        by_id = {it["i"]: it for it in items}
        for pid, verdict, note in (("p2", "on_topic", "stock market"), ("p3", "on_topic", "index funds")):
            recs = kb.emit_batches(man, man["_dir"], by_id, list(by_id), pid, "initial")
            Path(recs[0]["verdict_path"]).write_text(json.dumps(verdicts(items, verdict, note, ["stocks"])))
        code, out, err = _main(cc, monkeypatch, capsys, ["--manifest", str(out_dir), "--intensity", str(chans)])
        assert code == 0, err
        row = json.loads(out)["channels"][0]
        assert row["verdict"] == "on_topic" and row["votes"] == ["off_topic", "on_topic", "on_topic"]
        assert row["notes"] == "stock market"  # from an agreeing pass, not the losing first one
        assert {t["term"] for t in json.loads(out)["adjacent_terms"]} == {"betting", "stocks"}

    def test_channel_id_mismatch_is_fatal(self, ctx, cc, monkeypatch, capsys, tmp_path):
        out_dir, s, chans, _ = self._emit(ctx, monkeypatch, capsys, tmp_path)
        b = json.loads(Path(s["batches"][0]["path"]).read_text())
        Path(b["verdict_path"]).write_text(json.dumps([{"i": 0, "channel_id": 999, "verdict": "on_topic"}]))
        code, _, err = _main(cc, monkeypatch, capsys, ["--manifest", str(out_dir), "--intensity", str(chans)])
        assert code != 0 and "does not match" in err

    def test_bad_verdict_value_is_fatal(self, ctx, cc, monkeypatch, capsys, tmp_path):
        out_dir, s, chans, _ = self._emit(ctx, monkeypatch, capsys, tmp_path)
        b = json.loads(Path(s["batches"][0]["path"]).read_text())
        Path(b["verdict_path"]).write_text(json.dumps([{"i": 0, "channel_id": 1, "verdict": "yes"}]))
        code, _, err = _main(cc, monkeypatch, capsys, ["--manifest", str(out_dir), "--intensity", str(chans)])
        assert code != 0 and "must be one of" in err


class TestProbeMeasurements:
    def test_residual_and_exclusion_counts(self, probe, monkeypatch, capsys):
        def run(cmd, input=None, **kw):
            body = json.loads(input)
            q = json.dumps(body["query"])
            total = 100
            if "-(retirement)" in q:
                total = 30
            if '-scam' in q:
                total = 96
            env = {"results": [], "total": total, "aggregations": {"distinct_channels": {"value": total // 2}}}
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(env), stderr="")
        monkeypatch.setattr(probe.subprocess, "run", run)
        monkeypatch.setattr(probe.sys, "argv", ["probe.py", "--samples", "0", "--no-recency", "--no-cache",
                                                "--residual-vs", "retirement", "--exclude-phrase", "scam", "pension"])
        probe.main()
        k = json.loads(capsys.readouterr().out)["keywords"][0]
        assert k["documents"] == 100
        assert k["residual"] == {"vs": "retirement", "documents": 30, "channels": 15, "residual_share": 0.3}
        assert k["exclusion_checks"] == [{"phrase": "scam", "documents": 96, "channels": 48,
                                          "delta_pct_documents": 4.0, "delta_pct_channels": 4.0}]
