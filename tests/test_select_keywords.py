"""Tests for the tl-keyword-research select_keywords.py script (pure, no ES)."""
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


sk = _load()


def _probe(level="topic"):
    if level == "topic":
        return {
            "operator": "OR", "level": "topic",
            "keywords": [
                {"keyword": "tiktok shop", "count": 100, "samples": [
                    {"title": "Selling on TikTok Shop", "summary": "guide", "channel_id": 1, "url": "u1"},
                    {"title": "TikTok Shop tips", "summary": "more", "channel_id": 2, "url": "u2"},
                ]},
                {"keyword": "tiktok", "count": 9000, "samples": [
                    {"title": "TikTok dance compilation", "summary": "dances", "channel_id": 3, "url": "u3"},
                    {"title": "Funny TikToks", "summary": "lol", "channel_id": 4, "url": "u4"},
                ]},
            ],
            "dropped": [],
        }
    return {
        "operator": "OR", "level": "channel",
        "keywords": [
            {"keyword": "cooking", "count": 50, "samples": [
                {"name": "Chef Bob", "topic": "cooking and recipes", "channel_description": "d", "channel_id": 10},
            ]},
        ],
        "dropped": [],
    }


def _stdin(monkeypatch, obj):
    monkeypatch.setattr(sk.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sk.sys.stdin, "read", lambda: json.dumps(obj))


class TestEmitBatch:
    def test_topic_batch_deterministic_keys(self, monkeypatch, capsys):
        _stdin(monkeypatch, _probe("topic"))
        monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py", "--emit-batch"])
        sk.main()
        batch = json.loads(capsys.readouterr().out)
        assert [b["i"] for b in batch] == [0, 1, 2, 3]                  # deterministic
        assert batch[0] == {"i": 0, "keyword": "tiktok shop", "title": "Selling on TikTok Shop", "summary": "guide"}
        assert batch[2]["keyword"] == "tiktok"
        assert set(batch[0]) == {"i", "keyword", "title", "summary"}    # no metadata leaked

    def test_channel_batch_uses_name_topic(self, monkeypatch, capsys):
        _stdin(monkeypatch, _probe("channel"))
        monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py", "--emit-batch"])
        sk.main()
        batch = json.loads(capsys.readouterr().out)
        assert set(batch[0]) == {"i", "keyword", "name", "topic"}


class TestApply:
    def _apply(self, monkeypatch, capsys, tmp_path, verdict, level="topic"):
        vf = tmp_path / "verdict.json"
        vf.write_text(json.dumps(verdict))
        _stdin(monkeypatch, _probe(level))
        monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py", "--apply", str(vf)])
        sk.main()
        return json.loads(capsys.readouterr().out)

    def test_keeps_on_topic_drops_off_topic(self, monkeypatch, capsys, tmp_path):
        # tiktok shop samples (i 0,1) on-topic; tiktok samples (i 2,3) off-topic
        verdict = [{"i": 0, "relevant": True}, {"i": 1, "relevant": True},
                   {"i": 2, "relevant": False}, {"i": 3, "relevant": False}]
        out = self._apply(monkeypatch, capsys, tmp_path, verdict)
        assert [k["keyword"] for k in out["kept"]] == ["tiktok shop"]
        assert [d["keyword"] for d in out["dropped"]] == ["tiktok"]
        assert out["dropped"][0]["reason"] == "off_intent"
        assert out["groups"] == [{"text": "tiktok shop"}]

    def test_strict_majority_tie_drops(self, monkeypatch, capsys, tmp_path):
        # tiktok shop 1 of 2 relevant (tie) -> drop; tiktok 0 of 2 -> drop
        verdict = [{"i": 0, "relevant": True}, {"i": 1, "relevant": False},
                   {"i": 2, "relevant": False}, {"i": 3, "relevant": False}]
        out = self._apply(monkeypatch, capsys, tmp_path, verdict)
        assert out["kept"] == []

    def test_candidate_videos_from_relevant_only(self, monkeypatch, capsys, tmp_path):
        # tiktok shop kept (i0,i1 both relevant) -> both its videos are candidates;
        # tiktok dropped (i2,i3 off) -> contributes none, even though it had samples.
        verdict = [{"i": 0, "relevant": True}, {"i": 1, "relevant": True},
                   {"i": 2, "relevant": False}, {"i": 3, "relevant": False}]
        out = self._apply(monkeypatch, capsys, tmp_path, verdict)
        urls = [v["url"] for v in out["candidate_videos"]]
        assert urls == ["u1", "u2"]                 # only relevant samples of kept keywords

    def test_channel_candidates(self, monkeypatch, capsys, tmp_path):
        out = self._apply(monkeypatch, capsys, tmp_path, [{"i": 0, "relevant": True}], level="channel")
        assert out["candidate_channels"] == [{"channel_id": 10, "name": "Chef Bob", "topic": "cooking and recipes"}]
        assert "candidate_videos" not in out

    def test_majority_vote_across_passes(self, monkeypatch, capsys, tmp_path):
        # two passes; i0 True/True -> rel, i1 True/False -> tie=not rel (strict),
        # so tiktok shop 1 of 2 -> dropped
        p1 = tmp_path / "p1.json"; p1.write_text(json.dumps([{"i": 0, "relevant": True}, {"i": 1, "relevant": True}, {"i": 2, "relevant": False}, {"i": 3, "relevant": False}]))
        p2 = tmp_path / "p2.json"; p2.write_text(json.dumps([{"i": 0, "relevant": True}, {"i": 1, "relevant": False}, {"i": 2, "relevant": False}, {"i": 3, "relevant": False}]))
        _stdin(monkeypatch, _probe("topic"))
        monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py", "--apply", str(p1), str(p2)])
        sk.main()
        out = json.loads(capsys.readouterr().out)
        # i0 majority True, i1 majority False -> tiktok shop 1/2 -> dropped
        assert out["kept"] == []

    def test_unvalidated_when_no_samples(self, monkeypatch, capsys, tmp_path):
        probe = {"operator": "OR", "level": "topic",
                 "keywords": [{"keyword": "crypto", "count": 5, "samples": []}], "dropped": []}
        vf = tmp_path / "v.json"; vf.write_text("[]")
        _stdin(monkeypatch, probe)
        monkeypatch.setattr(sk.sys, "argv", ["select_keywords.py", "--apply", str(vf)])
        sk.main()
        out = json.loads(capsys.readouterr().out)
        assert out["unvalidated"] == [{"keyword": "crypto", "reason": "no_samples"}]
        assert out["kept"] == []


class TestVerdictCompleteness:
    """A verdict that doesn't cover every batch sample means the validator
    truncated — fail loudly by default, warn-and-continue with --allow-missing."""

    def _partial_verdicts(self):
        # _probe() has 4 topic samples (i = 0..3); cover only 0 and 1.
        return [{0: True, 1: True}]

    def test_missing_verdicts_fail_by_default(self, capsys):
        with pytest.raises(SystemExit) as exc:
            sk.apply_verdicts(_probe(), self._partial_verdicts())
        assert "no verdict" in str(exc.value)
        assert "2" in str(exc.value)  # 2 of 4 missing

    def test_allow_missing_warns_and_continues(self, capsys):
        sk.apply_verdicts(_probe(), self._partial_verdicts(), allow_missing=True)
        captured = capsys.readouterr()
        assert "warning" in captured.err
        out = json.loads(captured.out)
        # samples 0+1 relevant -> "tiktok shop" kept; "tiktok" got no verdicts -> dropped
        assert [k["keyword"] for k in out["kept"]] == ["tiktok shop"]

    def test_full_coverage_passes_silently(self, capsys):
        sk.apply_verdicts(_probe(), [{0: True, 1: True, 2: False, 3: False}])
        assert "warning" not in capsys.readouterr().err
